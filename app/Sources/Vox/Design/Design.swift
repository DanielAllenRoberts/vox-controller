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
            case .stopped, .failed: Button("Start Vox") { model.engine.start() }.buttonStyle(.borderedProminent)
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
