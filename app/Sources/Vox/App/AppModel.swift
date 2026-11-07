import Foundation
import Observation
import SwiftUI

/// Everything the windows and the menu bar share: the engine, the live conversation, settings.
@MainActor
@Observable
final class AppModel {
    let engine = EngineSupervisor()
    var api: APIClient { engine.api }

    /// Newest last. Seeded from /conversation/recent, then kept live over the websocket.
    private(set) var turns: [Turn] = []
    private(set) var settings: [Setting] = []
    var settingsError: String?

    /// Sidebar selection for the main window.
    var page: Page = .home

    private var stream: URLSessionWebSocketTask?
    private var streamTask: Task<Void, Never>?
    private var lastEngineRunning = false

    var onboardingDone: Bool {
        get { UserDefaults.standard.bool(forKey: "onboardingDone") }
        set { UserDefaults.standard.set(newValue, forKey: "onboardingDone") }
    }

    private var booted = false

    /// Start (or attach to) the engine and keep the live views fed. Safe to call more than once.
    func boot() {
        engine.start()
        guard !booted else { return }
        booted = true
        HoldToTalk.shared.start()
        Task { await watchEngine() }
    }

    /// Snapshot only: read from an already-running engine without ever launching one.
    func attachForSnapshot() {
        Task {
            if let s = try? await api.status() {
                engine.previewRunning(s)
                await reloadTurns()
                await reloadSettings()
            }
        }
    }

    /// Snapshot/preview only: fill the model with fixture data, no engine.
    func loadFixtures(turns: [Turn], settings: [Setting], status: EngineStatus) {
        // Same ordering as live data (the API is newest-first; the screen is oldest-first), so a
        // fixture can't hide an ordering bug the way an already-sorted one did.
        self.turns = turns.sorted { ($0.date ?? .distantPast) < ($1.date ?? .distantPast) }
        self.settings = settings
        engine.previewRunning(status)
    }

    /// Re-seed and re-subscribe whenever the engine (re)appears.
    private func watchEngine() async {
        while true {
            let running = engine.isRunning
            if running && !lastEngineRunning {
                connectStream()          // subscribe FIRST so nothing said meanwhile is missed…
                await reloadTurns()      // …then merge history in (duplicates are dropped)
                await reloadSettings()
            }
            lastEngineRunning = running
            try? await Task.sleep(for: .seconds(1))
        }
    }

    // MARK: Conversation

    /// The API returns newest FIRST; `turns` is oldest first (chat order). Merged, not replaced, so
    /// turns that arrived on the stream while this loaded aren't lost.
    func reloadTurns() async {
        guard let fetched = try? await api.recentTurns() else { return }
        var byID = Dictionary(turns.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        for t in fetched { byID[t.id] = t }
        turns = byID.values.sorted { ($0.date ?? .distantPast, $0.id) < ($1.date ?? .distantPast, $1.id) }
        if turns.count > 500 { turns.removeFirst(turns.count - 500) }
    }

    /// The live conversation feed. Reconnects on its own if the socket drops while the engine stays
    /// up; previously a dropped socket left Home, Conversation and the menu bar silently stale.
    private func connectStream() {
        stream?.cancel(with: .goingAway, reason: nil)
        streamTask?.cancel()
        streamTask = Task { [weak self] in
            var resync = false
            while !Task.isCancelled {
                guard let self, self.engine.isRunning else { return }
                let task = URLSession.shared.webSocketTask(with: self.api.conversationStream)
                self.stream = task
                task.resume()
                if resync { await self.reloadTurns() }   // catch up on anything said while disconnected
                while !Task.isCancelled {
                    guard let msg = try? await task.receive() else { break }
                    let data: Data?
                    switch msg {
                    case .string(let s): data = s.data(using: .utf8)
                    case .data(let d): data = d
                    @unknown default: data = nil
                    }
                    if let data, let turn = try? JSONDecoder().decode(Turn.self, from: data) {
                        self.append(turn)
                    }
                }
                resync = true
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func append(_ t: Turn) {
        guard !turns.contains(where: { $0.id == t.id }) else { return }
        turns.append(t)
        if turns.count > 500 { turns.removeFirst(turns.count - 500) }
    }

    /// Typed input: heard by Vox exactly as if spoken. The reply arrives on the conversation feed.
    /// The ⏹ button. nil if the engine couldn't be reached, else what was stopped (may be empty).
    func stopNow() async -> [String]? {
        try? await api.stop()
    }

    func say(_ text: String) async -> String? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        do { try await api.say(t); return nil } catch { return error.localizedDescription }
    }

    // MARK: Settings

    /// Models the ChatGPT provider offers, read live from OpenAI for the saved key ([] without one).
    var chatgptModels: [String] = []

    func loadChatGPTModels() async {
        struct R: Decodable { var models: [String] }
        if let r: R = try? await api.get("brain/models?provider=chatgpt") { chatgptModels = r.models }
    }

    func reloadSettings() async {
        do { settings = try await api.settings(); settingsError = nil }
        catch { settingsError = error.localizedDescription }
    }

    func setting(_ key: String) -> Setting? { settings.first { $0.key == key } }

    func value(_ key: String) -> JSONValue { setting(key)?.value ?? .null }

    /// Optimistic: update locally, then persist. On failure, re-read the true value and THEN show
    /// why. (Setting the error before the reload let the reload's success wipe it instantly.)
    func set(_ key: String, _ value: JSONValue) {
        if let i = settings.firstIndex(where: { $0.key == key }) { settings[i].value = value }
        Task {
            do { try await api.setSetting(key, value) }
            catch {
                let why = error.localizedDescription
                await reloadSettings()
                settingsError = "Couldn't change \u{201C}\(setting(key)?.label ?? key)\u{201D}: \(why)"
            }
        }
    }

    func binding(bool key: String) -> Binding<Bool> {
        Binding(get: { self.value(key).bool }, set: { self.set(key, .bool($0)) })
    }

    func binding(string key: String) -> Binding<String> {
        Binding(get: { self.value(key).string }, set: { self.set(key, .string($0)) })
    }

    /// A restart-only setting changed this session (shows "Restart Now" in Settings).
    private(set) var restartNeeded = false
    func noteRestartNeeded() { restartNeeded = true }

    func restartEngine() {
        restartNeeded = false
        engine.restart()
    }

    // MARK: Listening

    /// Set the moment the user flips Listening, so the switch moves immediately instead of snapping
    /// back until the next status poll. Cleared once the engine confirms (or refuses).
    private var pausedPending: Bool?
    var isPaused: Bool { pausedPending ?? engine.status?.paused ?? false }

    func togglePaused() {
        let next = !isPaused
        pausedPending = next
        Task {
            try? await api.setPaused(next)
            await engine.refreshStatus()
            pausedPending = nil
        }
    }
}

enum Page: String, CaseIterable, Identifiable, Hashable {
    case home, conversation, guide, personality, commands, vocabulary, rules, prompts, board, reminders, memory, activity, testing, voiceLab
    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: "Home"
        case .conversation: "Conversation"
        case .guide: "Guide"
        case .personality: "Personality"
        case .commands: "Commands"
        case .vocabulary: "Vocabulary"
        case .rules: "Rules"
        case .board: "Board"
        case .reminders: "Reminders"
        case .memory: "Memory"
        case .activity: "Activity"
        case .voiceLab: "Voice Lab"
        case .testing: "Testing"
        case .prompts: "Prompts"
        }
    }

    var symbol: String {
        switch self {
        case .home: "waveform"
        case .conversation: "bubble.left.and.bubble.right"
        case .guide: "book"
        case .personality: "person.crop.circle"
        case .commands: "command"
        case .vocabulary: "character.book.closed"
        case .rules: "list.bullet.rectangle"
        case .board: "rectangle.split.3x1"
        case .reminders: "alarm"
        case .memory: "brain"
        case .activity: "chart.bar.xaxis"
        case .voiceLab: "waveform.badge.mic"
        case .testing: "checklist"
        case .prompts: "text.alignleft"
        }
    }

    static let sections: [(String?, [Page])] = [
        (nil, [.home, .conversation, .guide]),
        ("Teach Vox", [.personality, .commands, .vocabulary, .rules, .prompts]),
        ("Organise", [.board, .reminders, .memory]),
        ("Insights", [.activity, .testing, .voiceLab]),
    ]
}
