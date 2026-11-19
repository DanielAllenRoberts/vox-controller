import AppKit
import SwiftUI

/// The corner indicator: a small pill in the top-right of the screen that says which mode Vox is in
/// and shows what it just heard, on top of whatever app or Space you're in.
///
/// It stays up while Vox is in a mode (control, dictation, talking), appears while you hold the talk
/// key or speak in a mode, shows each thing Vox recognised for a few seconds, and flashes briefly
/// when the mode changes or the mic is paused. At idle with nothing happening it's gone.
///
/// The panel never takes focus and clicks pass straight through it. Like the click badges and the
/// notification bubble it's excluded from screen capture, so it can't end up in Vox's own
/// screenshots of your screen.
@MainActor
final class HUD {
    static let shared = HUD()

    static var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "showHUD") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "showHUD"); shared.update() }
    }

    struct Event: Decodable {
        var type: String
        var on: Bool?
        var text: String?
        var ignored: Bool?
    }

    private enum Phase { case quiet, listening, recognising }

    private static let heardFor = 4.0        // how long a recognised line stays up
    private static let ignoredFor = 2.5      // idle speech that wasn't for Vox: shorter, and dimmed
    private static let recognisingFor = 4.0  // give up waiting for a transcript (silence, own echo)
    private static let flashFor = 3.0        // mode or pause changed
    private static let size = CGSize(width: 380, height: 120)

    private weak var model: AppModel?
    private var streamTask: Task<Void, Never>?
    private var panel: NSPanel?
    private let state = HUDState()

    private var phase = Phase.quiet
    private var phaseUntil = Date.distantPast
    private var line = ""
    private var lineDim = false
    private var lineUntil = Date.distantPast
    private var flashUntil = Date.distantPast
    private var lastTitle: String?
    private var recheck: DispatchWorkItem?

    /// Follow the engine's live events for as long as the app runs, reconnecting whenever it restarts.
    func start(_ model: AppModel) {
        guard streamTask == nil else { return }
        self.model = model
        streamTask = Task {
            while !Task.isCancelled {
                if model.engine.isRunning {
                    let ws = URLSession.shared.webSocketTask(with: model.api.hudStream)
                    ws.resume()
                    while let msg = try? await ws.receive() {
                        let data: Data? = switch msg {
                        case .string(let s): s.data(using: .utf8)
                        case .data(let d): d
                        @unknown default: nil
                        }
                        if let data, let e = try? JSONDecoder().decode(Event.self, from: data) { await self.handle(e) }
                    }
                    ws.cancel(with: .goingAway, reason: nil)
                    self.phase = .quiet
                    self.update()
                }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func handle(_ e: Event) async {
        let now = Date()
        switch e.type {
        case "state":
            await model?.engine.refreshStatus()
        case "listening":
            phase = e.on == true ? .listening : .recognising
            phaseUntil = e.on == true ? .distantFuture : now.addingTimeInterval(Self.recognisingFor)
        case "heard":
            phase = .quiet
            line = e.text ?? ""
            lineDim = e.ignored == true
            lineUntil = now.addingTimeInterval(lineDim ? Self.ignoredFor : Self.heardFor)
        default:
            return
        }
        update()
    }

    /// Work out what the pill should show right now, and whether it should be on screen at all.
    func update() {
        recheck?.cancel()
        guard let model else { return }
        let now = Date()
        let presence = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        if let last = lastTitle, last != presence.title { flashUntil = now.addingTimeInterval(Self.flashFor) }
        lastTitle = presence.title
        if phase != .quiet && now >= phaseUntil { phase = .quiet }

        let inMode = ["control", "assistant", "dictation"].contains(model.engine.status?.mode ?? "")
        let showLine = now < lineUntil && !line.isEmpty
        let visible = Self.enabled && model.engine.isRunning
            && (inMode || phase != .quiet || showLine || now < flashUntil)

        if visible {
            let text: String? = switch phase {
            case .listening: "Listening…"
            case .recognising: "…"
            case .quiet: showLine ? "\u{201C}\(line)\u{201D}" : nil
            }
            state.content = .init(presence: presence, text: text, dim: phase == .quiet && lineDim)
            show()
            // Come back when the next thing expires (a line, a flash, a transcript that never came).
            let next = [phaseUntil, lineUntil, flashUntil].filter { $0 > now && $0 != .distantFuture }.min()
            if let next {
                let work = DispatchWorkItem { [weak self] in self?.update() }
                recheck = work
                DispatchQueue.main.asyncAfter(deadline: .now() + next.timeIntervalSince(now) + 0.05, execute: work)
            }
        } else {
            hide()
        }
    }

    // MARK: Panel

    private func show() {
        let panel = self.panel ?? makePanel()
        self.panel = panel
        // Top-right of whichever screen the pointer is on: that's the one you're looking at.
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(mouse) } ?? NSScreen.main
        if let vf = screen?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: vf.maxX - Self.size.width - 10, y: vf.maxY - Self.size.height - 8))
        }
        if !panel.isVisible { panel.alphaValue = 0; panel.orderFrontRegardless() }
        panel.animator().alphaValue = 1
    }

    private func hide() {
        guard let panel, panel.isVisible else { return }
        NSAnimationContext.runAnimationGroup({ $0.duration = 0.25; panel.animator().alphaValue = 0 }) {
            Task { @MainActor in if panel.alphaValue == 0 { panel.orderOut(nil) } }
        }
    }

    private func makePanel() -> NSPanel {
        let p = NSPanel(contentRect: NSRect(origin: .zero, size: Self.size),
                        styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false
        p.level = .statusBar
        p.ignoresMouseEvents = true
        p.hidesOnDeactivate = false
        p.isReleasedWhenClosed = false
        p.sharingType = .none
        p.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        p.contentView = NSHostingView(rootView: HUDView(state: state))
        return p
    }
}

@MainActor
@Observable
final class HUDState {
    struct Content: Equatable {
        var presence: VoxPresence
        var text: String?
        var dim: Bool
    }
    var content: Content?
}

private struct HUDView: View {
    var state: HUDState

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.clear
            if let c = state.content { HUDPill(presence: c.presence, text: c.text, dim: c.dim) }
        }
        .animation(.easeOut(duration: 0.15), value: state.content)
    }
}

/// The pill itself: mode on top, what Vox is hearing (or just heard) underneath.
struct HUDPill: View {
    var presence: VoxPresence
    var text: String?
    var dim = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 7) {
                Circle().fill(presence.tone == .paused || presence.tone == .off ? Color.gray : presence.color)
                    .frame(width: 8, height: 8)
                Image(systemName: presence.symbol).font(.caption)
                Text(presence.tone == .idle ? "Vox" : presence.title).font(.callout.weight(.semibold))
            }
            if let text {
                Text(text)
                    .font(.callout)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                    .opacity(dim ? 0.55 : 1)
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(Color.black.opacity(0.8), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(.white.opacity(0.15)))
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: 360, alignment: .trailing)
        .accessibilityElement(children: .combine)
    }
}
