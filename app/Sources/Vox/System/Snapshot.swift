import AppKit
import SwiftUI

/// `Vox --snapshot <dir> [fixtures.json]`: renders every screen into PNGs, in light and dark, using
/// fixture data instead of a live engine, then exits.
///
/// This is how the UI gets reviewed without driving anyone's screen. Windows are drawn far
/// off-screen, the app never activates, and each window is captured by its own ID, so nothing
/// appears and focus never moves.
@MainActor
enum Snapshotter {
    struct Fixtures: Decodable {
        var status: EngineStatus
        var turns: [Turn]
        var settings: [Setting]
    }

    static func run(outDir: String, fixtures: String?) -> Never {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let out = URL(fileURLWithPath: outDir)
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

        let model = AppModel()
        if fixtures == "live" {
            // Real data from a running engine on :8765. Attach only: never start one.
            model.attachForSnapshot()
            RunLoop.main.run(until: Date().addingTimeInterval(3))
        } else if let path = fixtures, let data = FileManager.default.contents(atPath: path) {
            do {
                let f = try JSONDecoder().decode(Fixtures.self, from: data)
                model.loadFixtures(turns: f.turns, settings: f.settings, status: f.status)
            } catch {
                FileHandle.standardError.write(Data("fixtures: \(error)\n".utf8))
            }
        }
        let only = ProcessInfo.processInfo.environment["VOX_SNAPSHOT_ONLY"]

        for dark in [false, true] {
            app.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            let suffix = dark ? "dark" : "light"
            var shots: [(String, () -> AnyView, CGSize)] = []
            for page in Page.allCases {
                shots.append(("page-\(page.rawValue)", { AnyView(PageHost(page: page).environment(model)) }, CGSize(width: 1000, height: 680)))
            }
            for tab in SettingsTab.allCases {
                shots.append(("settings-\(tab.rawValue)", { AnyView(SettingsTabHost(tab: tab).environment(model)) }, CGSize(width: 620, height: 600)))
            }
            for step in OnboardingView.Step.allCases {
                shots.append(("onboarding-\(step.rawValue)-\(step)", { AnyView(OnboardingView(step: step, aboutYou: .sample, meterPreview: MicLevel(live: true, level: 0.58, threshold: 0.27)).environment(model)) }, CGSize(width: 640, height: 620)))
            }
            shots.append(("board-card-editor", {
                AnyView(CardEditor(card: BoardCard(id: 1, listId: 1, title: "Send the Acme invoice", body: "Net 30, attach the timesheet.",
                                                   tags: ["work", "money"], position: 0, due: "2026-11-13",
                                                   checklist: [ChecklistItem(text: "Draft it", done: true), ChecklistItem(text: "Send it", done: false)]),
                                   onSave: { _ in }, onArchive: {}, onDelete: {}).environment(model))
            }, CGSize(width: 480, height: 640)))
            shots.append(("connections-composio-sheet", { AnyView(AddConnectionSheet(preset: .composio) { _ in }.environment(model)) }, CGSize(width: 500, height: 420)))
            // (name, mode, text, has ■, speech paused or nil for no pause button)
            let hud: [(String, String, String?, Bool, Bool?)] = [("control-heard", "control", "\u{201C}next tab\u{201D}", true, nil),
                                                                 ("assistant-speaking", "assistant", "Speaking…", true, false),
                                                                 ("agent-paused", "idle", "Speech paused", true, true),
                                                                 ("mode-flash", "idle", nil, false, nil)]
            for (name, mode, text, stop, paused) in hud {
                var s = model.engine.status
                s?.mode = mode
                let p = VoxPresence.from(engine: .running(owned: true), status: s)
                shots.append(("hud-\(name)", {
                    AnyView(HUDPill(presence: p, text: text, onStop: stop ? {} : nil, speechPaused: paused).padding(12)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing).background(.gray))
                }, CGSize(width: 380, height: 120)))
            }
            shots.append(("menubar", { AnyView(Roots.menuBar(model).background(.regularMaterial)) }, CGSize(width: 320, height: 600)))

            for (name, view, size) in shots where only.map({ name.contains($0) }) ?? true {
                if let png = render(view(), size: size) {
                    try? png.write(to: out.appending(path: "\(name)-\(suffix).png"))
                }
            }
        }
        print("snapshots → \(out.path)")
        exit(0)
    }

    private static func render(_ view: AnyView, size: CGSize) -> Data? {
        let host = NSHostingView(rootView: view.frame(width: size.width, height: size.height))
        let win = OffscreenWindow(contentRect: NSRect(origin: .zero, size: size),
                                  styleMask: [.titled, .fullSizeContentView], backing: .buffered, defer: false)
        win.titlebarAppearsTransparent = true
        win.titleVisibility = .hidden
        win.contentView = host
        win.setFrameOrigin(NSPoint(x: -20000, y: -20000))
        win.orderFrontRegardless()
        win.setFrameOrigin(NSPoint(x: -20000, y: -20000))
        // Let SwiftUI lay out, load async state and settle animations.
        RunLoop.main.run(until: Date().addingTimeInterval(1.2))
        defer { win.orderOut(nil) }
        guard let img = captureWindow(win.windowNumber) else { return nil }
        return NSBitmapImageRep(cgImage: img).representation(using: .png, properties: [:])
    }

    /// CGWindowListCreateImage is deprecated in the SDK but still works for an app's own windows
    /// (no Screen Recording permission needed); look it up at runtime so the build stays clean.
    private static func captureWindow(_ id: Int) -> CGImage? {
        typealias Fn = @convention(c) (CGRect, UInt32, UInt32, UInt32) -> Unmanaged<CGImage>?
        guard let sym = dlsym(dlopen(nil, RTLD_NOW), "CGWindowListCreateImage") else { return nil }
        let fn = unsafeBitCast(sym, to: Fn.self)
        // kCGWindowListOptionIncludingWindow, kCGWindowImageBoundsIgnoreFraming
        return fn(.null, 1 << 3, UInt32(id), 1 << 0)?.takeRetainedValue()
    }
}

/// A window macOS isn't allowed to pull back on-screen.
private final class OffscreenWindow: NSWindow {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

private struct PageHost: View {
    @Environment(AppModel.self) private var model
    var page: Page
    var body: some View {
        Roots.main(model).onAppear { model.page = page }
    }
}

private struct SettingsTabHost: View {
    var tab: SettingsTab
    init(tab: SettingsTab) {
        self.tab = tab
        UserDefaults.standard.set(tab.rawValue, forKey: "settingsTab")
    }
    var body: some View { SettingsView() }
}
