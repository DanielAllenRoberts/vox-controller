import SwiftUI

/// The menu bar panel: what Vox is doing, a box to type to it, the last thing it said, and the
/// two switches people reach for most (pause the mic, mute replies).
struct MenuBarView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                StatusOrb(presence: p, size: 10)
                VStack(alignment: .leading, spacing: 1) {
                    Text(p.title).font(.headline)
                    Text(p.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
                Spacer(minLength: 0)
            }

            if model.engine.isRunning {
                AskField(compact: true)
                if let last = model.turns.last(where: { !$0.isUser }) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Vox said").font(.caption).foregroundStyle(.secondary)
                        Text(last.text).font(.callout).lineLimit(4).textSelection(.enabled)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                VStack(spacing: 6) {
                    SwitchRow("Listening", isOn: Binding(get: { !model.isPaused }, set: { _ in model.togglePaused() }))
                    SwitchRow("Speak replies", isOn: model.binding(bool: "tts_enabled"))
                }
                .toggleStyle(.switch).controlSize(.small)
            } else {
                switch model.engine.state {
                case .stopped, .failed: Button("Start Vox") { model.engine.start() }.buttonStyle(.borderedProminent)
                case .notInstalled: Button("Set Up Vox…") { show("onboarding") }.buttonStyle(.borderedProminent)
                default: ProgressView().controlSize(.small)
                }
            }

            Divider()
            HStack {
                Button("Open Vox") { show("main") }
                SettingsLink { Text("Settings…") }
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }
            }
            .buttonStyle(.borderless)
        }
        .padding(14)
        .frame(width: 320)
    }

    private func show(_ id: String) {
        openWindow(id: id)
        NSApp.activate()
    }
}

/// The menu bar icon follows Vox's state: a waveform while it's listening, slashed when paused.
struct MenuBarIcon: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        let name = switch p.tone {
        case .paused: "mic.slash"
        case .off: "waveform.slash"
        case .problem: "exclamationmark.triangle"
        case .typing: "keyboard"
        case .talking: "waveform.badge.mic"
        default: "waveform"
        }
        Image(systemName: name)
    }
}
