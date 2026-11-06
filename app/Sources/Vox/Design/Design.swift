import SwiftUI

// Vox's design vocabulary. Deliberately small: system materials, SF Symbols, semantic colours and
// the platform's own spacing. Native components do the heavy lifting and pick up Liquid Glass on
// macOS 26. Everything custom lives here so pages can't drift apart.

enum Metrics {
    static let page: CGFloat = 24          // outer padding of a page
    static let gap: CGFloat = 16           // between blocks
    static let tight: CGFloat = 8          // inside a block
    static let radius: CGFloat = 14        // card corners
    static let contentWidth: CGFloat = 760 // readable max width for single-column pages
}

/// What Vox is doing right now, in words a person would use.
struct VoxPresence: Equatable {
    enum Tone { case off, idle, active, talking, typing, paused, problem }

    var title: String
    var detail: String
    var tone: Tone
    var symbol: String

    var color: Color {
        switch tone {
        case .off, .paused: .secondary
        case .idle: .green
        case .active: .accentColor
        case .talking: .purple
        case .typing: .orange
        case .problem: .red
        }
    }

    static func from(engine: EngineSupervisor.State, status: EngineStatus?) -> VoxPresence {
        switch engine {
        case .notInstalled:
            return .init(title: "Not set up", detail: "Finish setup to start Vox.", tone: .off, symbol: "wrench.and.screwdriver")
        case .stopped:
            return .init(title: "Vox is off", detail: "Start Vox to use your voice.", tone: .off, symbol: "power")
        case .starting:
            return .init(title: "Starting…", detail: "Loading speech models.", tone: .off, symbol: "hourglass")
        case .failed(let why):
            return .init(title: "Vox stopped", detail: why, tone: .problem, symbol: "exclamationmark.triangle.fill")
        case .running:
            break
        }
        if status?.paused == true {
            return .init(title: "Paused", detail: "The microphone is ignored. Typing still works.", tone: .paused, symbol: "mic.slash.fill")
        }
        switch status?.mode ?? "idle" {
        case "control":
            return .init(title: "In control", detail: "Say a command. \"Stand down\" to stop.", tone: .active, symbol: "command")
        case "assistant":
            return .init(title: "Talking", detail: "Ask anything. \"Goodbye\" to finish.", tone: .talking, symbol: "bubble.left.and.bubble.right.fill")
        case "dictation":
            return .init(title: "Dictating", detail: "Everything you say is typed. \"Stop typing\" to finish.", tone: .typing, symbol: "keyboard")
        case "starting":
            return .init(title: "Starting…", detail: "Loading speech models.", tone: .off, symbol: "hourglass")
        default:
            return .init(title: "Listening", detail: "Say \"Hey Vox\" or \"Take control\".", tone: .idle, symbol: "waveform")
        }
    }
}

/// The breathing dot that says "Vox is alive". Calm at idle, brighter when Vox is engaged.
struct StatusOrb: View {
    var presence: VoxPresence
    var size: CGFloat = 12
    @State private var pulse = false

    private var animated: Bool { [.idle, .active, .talking, .typing].contains(presence.tone) }

    var body: some View {
        ZStack {
            if animated {
                Circle()
                    .fill(presence.color.opacity(0.35))
                    .scaleEffect(pulse ? 2.1 : 1)
                    .opacity(pulse ? 0 : 1)
            }
            Circle().fill(presence.color.gradient)
        }
        .frame(width: size, height: size)
        .onAppear { restart() }
        .onChange(of: presence.tone) { _, _ in restart() }
        .accessibilityLabel(presence.title)
    }

    private func restart() {
        pulse = false
        guard animated else { return }
        withAnimation(.easeOut(duration: presence.tone == .idle ? 2.4 : 1.4).repeatForever(autoreverses: false)) {
            pulse = true
        }
    }
}

/// A rounded, softly filled container for grouping on non-Form pages.
struct Card<Content: View>: View {
    var padding: CGFloat = Metrics.gap
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous).strokeBorder(.separator.opacity(0.5)))
    }
}

/// Standard page frame: a scroll view with consistent margins and a readable width.
struct PageScroll<Content: View>: View {
    var maxWidth: CGFloat? = Metrics.contentWidth
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Metrics.gap) { content }
                .frame(maxWidth: maxWidth ?? .infinity, alignment: .leading)
                .padding(Metrics.page)
                .frame(maxWidth: .infinity)
        }
    }
}

/// Small grey heading above a group, like Settings' section headers.
struct SectionLabel: View {
    var text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            .padding(.leading, 4)
    }
}

/// Shown when the engine isn't reachable, in place of a page's content.
struct EngineOffView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        ContentUnavailableView {
            Label(p.title, systemImage: p.symbol)
        } description: {
            Text(p.detail)
        } actions: {
            switch model.engine.state {
            case .stopped, .failed: Button("Start Vox") { model.boot() }.buttonStyle(.borderedProminent)
            case .notInstalled: Button("Open Setup…") { NotificationCenter.default.post(name: .voxShowOnboarding, object: nil) }
                .buttonStyle(.borderedProminent)
            default: ProgressView().controlSize(.small)
            }
        }
    }
}

/// Wraps a page that needs the engine: shows `EngineOffView` until it's reachable.
struct RequiresEngine<Content: View>: View {
    @Environment(AppModel.self) private var model
    @ViewBuilder var content: Content
    var body: some View {
        if model.engine.isRunning { content } else { EngineOffView() }
    }
}

/// Shown when Vox.app has a permission the running engine doesn't see yet. A process keeps the
/// answer it started with, so a grant made while the engine runs needs one restart to take effect.
struct PermissionLagBanner: View {
    @Environment(AppModel.self) private var model
    @State private var perms = Permissions()

    private var lagging: [String] {
        guard let seen = model.engine.status?.permissions else { return [] }
        var out: [String] = []
        if perms.status(.accessibility) == .granted && seen["accessibility"] == false { out.append("Accessibility") }
        if perms.status(.screenRecording) == .granted && seen["screenRecording"] == false { out.append("Screen Recording") }
        return out
    }

    var body: some View {
        if !lagging.isEmpty {
            HStack(spacing: 12) {
                Image(systemName: "arrow.clockwise.circle.fill").font(.title2).foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Restart Vox to finish turning on \(lagging.joined(separator: " and "))").font(.headline)
                    Text("Vox was already running when you allowed it.").font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Restart") { model.engine.restart() }.controlSize(.large)
            }
            .padding(Metrics.gap)
            .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous))
            .onAppear { perms.refresh() }
        }
    }
}

extension Notification.Name {
    static let voxShowOnboarding = Notification.Name("voxShowOnboarding")
}

extension Date {
    /// "Just now", "5 min ago", "Yesterday 14:02", "3 Nov".
    var friendly: String {
        let s = -timeIntervalSinceNow
        if s < 45 { return "Just now" }
        if s < 3600 { return "\(Int(s / 60)) min ago" }
        if Calendar.current.isDateInToday(self) { return formatted(date: .omitted, time: .shortened) }
        if Calendar.current.isDateInYesterday(self) { return "Yesterday " + formatted(date: .omitted, time: .shortened) }
        return formatted(.dateTime.day().month(.abbreviated))
    }
}

/// Label on the left, switch flush right: the alignment macOS uses in Settings, outside a Form.
struct SwitchRow: View {
    var title: String
    @Binding var isOn: Bool
    init(_ title: String, isOn: Binding<Bool>) { self.title = title; _isOn = isOn }

    var body: some View {
        HStack {
            Text(title)
            Spacer(minLength: 12)
            Toggle(title, isOn: $isOn).labelsHidden().toggleStyle(.switch).controlSize(.small)
        }
    }
}

// MARK: Errors and refreshing

/// Why a request failed, in words a person would use. A connection failure means Vox isn't
/// answering. The engine's own message is passed on only when it reads like a sentence for people;
/// most of its messages are written for developers ("'text' is required and must be…").
enum ErrorWords {
    static func reason(_ error: Error) -> String {
        if let api = error as? APIClient.APIError {
            if (400..<500).contains(api.status), let m = readable(api.message) { return m }
            return "Something went wrong."
        }
        if let url = error as? URLError, unreachable.contains(url.code) { return "Vox isn't responding. Is it running?" }
        return "Something went wrong."
    }

    /// "Couldn't add that rule. Vox isn't responding. Is it running?"
    static func message(_ what: String, _ error: Error) -> String { "\(what) \(reason(error))" }

    private static let unreachable: Set<URLError.Code> = [
        .cannotConnectToHost, .cannotFindHost, .networkConnectionLost, .notConnectedToInternet, .timedOut,
    ]

    private static let codeCharacters = CharacterSet(charactersIn: "_{}[]<>=|:()/\\")
    private static let jargon = [
        "required", "must be", "expected", "unknown", "invalid", "provide", "could not", "failed",
        "not found", "module", "json", "null", " id",
    ]

    private static func readable(_ message: String) -> String? {
        let t = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (3...160).contains(t.count), !t.unicodeScalars.contains(where: codeCharacters.contains),
              !jargon.contains(where: t.lowercased().contains) else { return nil }
        let s = t.prefix(1).uppercased() + t.dropFirst()
        return ".!?".contains(s.last ?? ".") ? s : s + "."
    }
}

/// A failed request, shown in place at the top of a page. Never a modal; the same on every page.
struct ErrorBanner: View {
    var message: String
    var dismiss: (() -> Void)?

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            Text(message).lineLimit(3).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            if let dismiss {
                Button("Dismiss", systemImage: "xmark", action: dismiss)
                    .labelStyle(.iconOnly).buttonStyle(.borderless).foregroundStyle(.secondary)
                    .help("Dismiss")
            }
        }
        .font(.callout)
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

/// Takes a page's place when its first load fails, with a way to try again.
struct LoadErrorView: View {
    var title: String
    var message: String
    var retry: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button("Try Again", action: retry)
        }
    }
}

extension View {
    /// Pins an `ErrorBanner` above the page. `error` is the latest change that failed; `loadError`
    /// the latest refresh that failed, which only gets a banner once the page has loaded (before
    /// that, `LoadErrorView` stands in for the page). Dismissing clears both.
    func pageErrors(_ error: Binding<String?>, loadError: Binding<String?>, loaded: Bool) -> some View {
        let message = error.wrappedValue ?? (loaded ? loadError.wrappedValue.map { "Couldn't refresh. \($0)" } : nil)
        return safeAreaInset(edge: .top, spacing: 0) {
            if let message {
                ErrorBanner(message: message) {
                    withAnimation(.smooth) { error.wrappedValue = nil; loadError.wrappedValue = nil }
                }
                .padding(.horizontal, Metrics.page).padding(.top, Metrics.tight)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.smooth, value: message)
    }

    /// Keeps a page current: loads when the page appears, again whenever Vox comes back to the
    /// front, and from the toolbar's Refresh button (⌘R). Things done by voice show up without
    /// leaving the page.
    func refreshesPage(_ load: @escaping @MainActor () async -> Void) -> some View {
        task { await load() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
                Task { await load() }
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("Refresh", systemImage: "arrow.clockwise") { Task { await load() } }
                        .keyboardShortcut("r", modifiers: .command)
                        .help("Refresh (⌘R)")
                }
            }
    }
}
