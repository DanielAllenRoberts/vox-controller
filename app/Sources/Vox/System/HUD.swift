import AppKit
import SwiftUI

/// The corner indicator: a small pill in the top-right of the screen that says which mode Vox is in
/// and shows what it just heard, on top of whatever app or Space you're in.
///
/// It stays up while Vox is in a mode (control, dictation, talking) or anything is speaking (Vox, or
/// an agent through the MCP), appears while you hold the talk key or speak in a mode, shows each
/// thing Vox recognised for a few seconds, and flashes briefly when the mode changes or the mic is
/// paused. At idle with nothing happening it's gone.
///
/// While it has something to stop it carries two buttons: ■ stops whatever is going on and drops
/// Vox back to idle, and ⏸ pauses speech (it carries on from the same sentence when you press ▶).
///
/// The panel never takes focus; without buttons, clicks pass straight through it. Like the click
/// badges and the notification bubble it's excluded from screen capture, so it can't end up in
/// Vox's own screenshots of your screen.
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
        var who: String?
        var paused: Bool?
    }

    private enum Phase { case quiet, listening, recognising }

    private static let heardFor = 4.0        // how long a recognised line stays up
    private static let recognisingFor = 4.0  // give up waiting for a transcript (silence, own echo)
    private static let flashFor = 3.0        // mode or pause changed

    private weak var model: AppModel?
    private var streamTask: Task<Void, Never>?
    private var panel: NSPanel?
    private var hosting: ClickThroughHost?

    private var phase = Phase.quiet
    private var phaseUntil = Date.distantPast
    private var line = ""
    private var speaker = ""          // who is speaking: "", "vox" or an agent's name
    private var speechPaused = false
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
                    self.speaker = ""
                    self.speechPaused = false
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
            lineUntil = now.addingTimeInterval(Self.heardFor)
        case "speech":
            speaker = e.who ?? ""
            speechPaused = e.paused == true
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
        let speaking = !speaker.isEmpty || speechPaused
        let visible = Self.enabled && model.engine.isRunning
            && (inMode || phase != .quiet || showLine || speaking || now < flashUntil)

        if visible {
            let text: String? = switch phase {
            case .listening: "Listening…"
            case .recognising: "…"
            case .quiet:
                if speechPaused { "Speech paused" }
                else if showLine { "\u{201C}\(line)\u{201D}" }
                else if speaker == "vox" { "Speaking…" }
                else if !speaker.isEmpty { "\(speaker) is speaking…" }
                else { nil }
            }
            let canStop = inMode || phase != .quiet || speaking
            show(HUDPill(presence: presence, text: text,
                         onStop: canStop ? { [weak self] in self?.stop() } : nil,
                         speechPaused: speaking ? speechPaused : nil,
                         onPause: { [weak self] in self?.togglePause() }))
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

    // MARK: Buttons

    /// ■: stop whatever is going on (speech from anyone, a brain call, an agent run) and go idle.
    private func stop() {
        guard let api = model?.api else { return }
        Task { _ = try? await api.stop(sleep: true) }
    }

    private func togglePause() {
        guard let api = model?.api else { return }
        speechPaused.toggle()   // move now; the engine's next "speech" event confirms it
        let paused = speechPaused
        update()
        Task { try? await api.post("speech", ["paused": .bool(paused)]) }
    }

    // MARK: Panel

    private func show(_ pill: HUDPill) {
        let panel = self.panel ?? makePanel()
        self.panel = panel
        hosting?.rootView = pill
        panel.ignoresMouseEvents = pill.onStop == nil && pill.speechPaused == nil
        // The panel is exactly the pill, so with buttons showing it only takes clicks on itself.
        // Top-right of whichever screen the pointer is on: that's the one you're looking at.
        let size = hosting?.fittingSize ?? .zero
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(mouse) } ?? NSScreen.main
        if let vf = screen?.visibleFrame {
            panel.setFrame(NSRect(x: vf.maxX - size.width - 10, y: vf.maxY - size.height - 8,
                                  width: size.width, height: size.height), display: true)
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
        let p = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false
        p.level = .statusBar
        p.hidesOnDeactivate = false
        p.isReleasedWhenClosed = false
        p.sharingType = .none
        p.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        let host = ClickThroughHost(rootView: HUDPill(presence: .init(title: "", detail: "", tone: .off, symbol: "waveform")))
        hosting = host
        p.contentView = host
        return p
    }
}

/// The buttons must work on the first click even though the panel is never the key window.
private final class ClickThroughHost: NSHostingView<HUDPill> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// The pill itself: mode on top, what Vox is hearing (or just heard) underneath, and the stop and
/// pause buttons on the right while there's something to stop or pause.
struct HUDPill: View {
    var presence: VoxPresence
    var text: String?
    var onStop: (() -> Void)?
    /// nil hides the pause button; otherwise whether speech is paused right now.
    var speechPaused: Bool?
    var onPause: () -> Void = {}

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 7) {
                    Circle().fill(presence.tone == .paused || presence.tone == .off ? Color.gray : presence.color)
                        .frame(width: 8, height: 8)
                    Image(systemName: presence.symbol).font(.caption)
                    Text(presence.tone == .idle ? "Vox" : presence.title).font(.callout.weight(.semibold))
                }
                if let text {
                    Text(text).font(.callout).lineLimit(3).multilineTextAlignment(.leading)
                }
            }
            if onStop != nil || speechPaused != nil {
                HStack(spacing: 6) {
                    if let speechPaused {
                        button(speechPaused ? "play.fill" : "pause.fill",
                               speechPaused ? "Carry on speaking" : "Pause speaking", onPause)
                    }
                    if let onStop { button("stop.fill", "Stop, and go back to idle", onStop) }
                }
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(Color.black.opacity(0.8), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(.white.opacity(0.15)))
        .frame(maxWidth: 360)
        .fixedSize()
        .accessibilityElement(children: .contain)
    }

    private func button(_ symbol: String, _ label: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 11, weight: .bold))
                .frame(width: 26, height: 26)
                .background(.white.opacity(0.18), in: Circle())
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .help(label)
        .accessibilityLabel(label)
    }
}
