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
        self.turns = turns
        self.settings = settings
        engine.previewRunning(status)
    }

    /// Re-seed and re-subscribe whenever the engine (re)appears.
    private func watchEngine() async {
        while true {
            let running = engine.isRunning
            if running && !lastEngineRunning {
                await reloadTurns()
                await reloadSettings()
                connectStream()
            }
            lastEngineRunning = running
            try? await Task.sleep(for: .seconds(1))
        }
    }

    // MARK: Conversation

    func reloadTurns() async {
        if let t = try? await api.recentTurns() { turns = t }
    }

    private func connectStream() {
        stream?.cancel(with: .goingAway, reason: nil)
        streamTask?.cancel()
        let task = URLSession.shared.webSocketTask(with: api.conversationStream)
        stream = task
        task.resume()
        streamTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let msg = try? await task.receive() else { break }
                let data: Data?
                switch msg {
                case .string(let s): data = s.data(using: .utf8)
                case .data(let d): data = d
                @unknown default: data = nil
                }
                if let data, let turn = try? JSONDecoder().decode(Turn.self, from: data) {
                    self?.append(turn)
                }
            }
        }
    }

    private func append(_ t: Turn) {
        guard !turns.contains(where: { $0.id == t.id }) else { return }
        turns.append(t)
        if turns.count > 500 { turns.removeFirst(turns.count - 500) }
    }

    /// Typed input: heard by Vox exactly as if spoken. The reply arrives on the conversation feed.
    func say(_ text: String) async -> String? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        do { try await api.say(t); return nil } catch { return error.localizedDescription }
    }

    // MARK: Settings

    func reloadSettings() async {
        do { settings = try await api.settings(); settingsError = nil }
        catch { settingsError = error.localizedDescription }
    }

    func setting(_ key: String) -> Setting? { settings.first { $0.key == key } }

    func value(_ key: String) -> JSONValue { setting(key)?.value ?? .null }

    /// Optimistic: update locally, then persist. Re-reads on failure so the UI never lies.
    func set(_ key: String, _ value: JSONValue) {
        if let i = settings.firstIndex(where: { $0.key == key }) { settings[i].value = value }
        Task {
            do { try await api.setSetting(key, value) }
            catch { settingsError = error.localizedDescription; await reloadSettings() }
        }
    }

    func binding(bool key: String) -> Binding<Bool> {
        Binding(get: { self.value(key).bool }, set: { self.set(key, .bool($0)) })
    }

    func binding(string key: String) -> Binding<String> {
        Binding(get: { self.value(key).string }, set: { self.set(key, .string($0)) })
    }

    // MARK: Listening

    var isPaused: Bool { engine.status?.paused ?? false }

    func togglePaused() {
        let next = !isPaused
        Task { try? await api.setPaused(next) }
    }
}

enum Page: String, CaseIterable, Identifiable, Hashable {
    case home, conversation, personality, commands, vocabulary, rules, board, reminders, memory, activity
    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: "Home"
        case .conversation: "Conversation"
        case .personality: "Personality"
        case .commands: "Commands"
        case .vocabulary: "Vocabulary"
        case .rules: "Rules"
        case .board: "Board"
        case .reminders: "Reminders"
        case .memory: "Memory"
        case .activity: "Activity"
        }
    }

    var symbol: String {
        switch self {
        case .home: "waveform"
        case .conversation: "bubble.left.and.bubble.right"
        case .personality: "person.crop.circle"
        case .commands: "command"
        case .vocabulary: "character.book.closed"
        case .rules: "list.bullet.rectangle"
        case .board: "rectangle.split.3x1"
        case .reminders: "alarm"
        case .memory: "brain"
        case .activity: "chart.bar.xaxis"
        }
    }

    static let sections: [(String?, [Page])] = [
        (nil, [.home, .conversation]),
        ("Teach Vox", [.personality, .commands, .vocabulary, .rules]),
        ("Organise", [.board, .reminders, .memory]),
        ("Insights", [.activity]),
    ]
}
