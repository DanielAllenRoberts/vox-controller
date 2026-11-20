import AppKit
import SwiftUI

@main
struct VoxApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    init() {
        // `Vox --snapshot <dir> [fixtures.json]` renders every screen to PNGs off-screen and exits.
        let args = CommandLine.arguments
        // `Vox --notify <title> <body>` posts one macOS notification and exits (see Notifier).
        if let i = args.firstIndex(of: "--notify"), i + 2 < args.count {
            Notifier.run(title: args[i + 1], body: args[i + 2])
        }
        if let i = args.firstIndex(of: "--snapshot"), i + 1 < args.count {
            Snapshotter.run(outDir: args[i + 1], fixtures: i + 2 < args.count ? args[i + 2] : nil)
        }
    }

    var body: some Scene {
        Window("Vox", id: "main") {
            Roots.main(delegate.model)
        }
        .defaultSize(width: 1000, height: 680)

        Window("Set Up Vox", id: "onboarding") {
            OnboardingView().environment(delegate.model)
        }
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)

        Settings {
            SettingsView().environment(delegate.model)
        }

        MenuBarExtra {
            Roots.menuBar(delegate.model)
        } label: {
            MenuBarIcon().environment(delegate.model).accessibilityLabel("Vox")
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Notifier.askPermission()
        if model.onboardingDone { model.boot() } else { model.engine.refreshLocation() }
    }

    /// Closing the window leaves Vox running in the menu bar.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) {
        HoldToTalk.shared.releaseForQuit()
        let quitEngine = UserDefaults.standard.object(forKey: "quitEngineWithApp") as? Bool ?? true
        if quitEngine { model.engine.stopForQuit() }
    }
}

/// The exact view trees the scenes show, shared with the snapshotter so its renders exercise the
/// real wiring. The environment goes OUTERMOST: OpensOnboarding reads AppModel too, and a modifier
/// applied outside `.environment` can't see it (that crashed Vox at launch once).
enum Roots {
    @MainActor static func main(_ model: AppModel) -> some View {
        MainWindow().modifier(OpensOnboarding()).environment(model)
    }

    @MainActor static func menuBar(_ model: AppModel) -> some View {
        MenuBarView().modifier(OpensOnboarding()).environment(model)
    }
}

/// Opens Setup on first launch (instead of the main window) and whenever something asks for it.
private struct OpensOnboarding: ViewModifier {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    func body(content: Content) -> some View {
        content
            .onAppear {
                if !model.onboardingDone {
                    openWindow(id: "onboarding")
                    dismissWindow(id: "main")
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .voxShowOnboarding)) { _ in
                openWindow(id: "onboarding")
                dismissWindow(id: "main")   // Setup on its own; it reopens the main window at the end
                NSApp.activate()
            }
    }
}
