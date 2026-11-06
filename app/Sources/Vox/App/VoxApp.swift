import AppKit
import SwiftUI

@main
struct VoxApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    init() {
        // `Vox --snapshot <dir> [fixtures.json]` renders every screen to PNGs off-screen and exits.
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--snapshot"), i + 1 < args.count {
            Snapshotter.run(outDir: args[i + 1], fixtures: i + 2 < args.count ? args[i + 2] : nil)
        }
    }

    var body: some Scene {
        Window("Vox", id: "main") {
            MainWindow()
                .environment(delegate.model)
                .modifier(OpensOnboarding())
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
            MenuBarView()
                .environment(delegate.model)
                .modifier(OpensOnboarding())
        } label: {
            MenuBarIcon().environment(delegate.model)
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
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
                NSApp.activate()
            }
    }
}
