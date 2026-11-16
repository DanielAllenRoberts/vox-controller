import SwiftUI

/// The menu bar panel: what Vox is doing, a box to type to it, the last thing it said, and the
/// two switches people reach for most (pause the mic, mute replies).
struct MenuBarView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        let last = model.turns.last(where: { !$0.isUser })
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                StatusOrb(presence: p, size: 10)
                VStack(alignment: .leading, spacing: 1) {
                    Text(p.title).font(.headline)
                    Text(p.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2, reservesSpace: true)
                }
                Spacer(minLength: 0)
            }

            if model.engine.isRunning {
                AskField(compact: true)
                // Always the same size (4 lines reserved): a panel that grows and shrinks with each reply
                // re-anchors under the menu bar and jumps about while you're looking at it.
                Group {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Vox said").font(.caption).foregroundStyle(.secondary)
                        Text(last?.text ?? "Nothing yet.").font(.callout)
                            .foregroundStyle(last == nil ? .secondary : .primary)
                            .lineLimit(4, reservesSpace: true).textSelection(.enabled)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                VStack(spacing: 6) {
                    SwitchRow("Listening", isOn: Binding(get: { !model.isPaused }, set: { _ in model.togglePaused() }))
                    SwitchRow("Speak replies", isOn: model.binding(bool: "tts_enabled"))
                    MicPicker()
                }
                .toggleStyle(.vox)
            } else {
                switch model.engine.state {
                case .stopped, .failed: Button("Start Vox") { model.boot() }.buttonStyle(.borderedProminent)
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

/// Which microphone Vox listens to, switchable on the spot (e.g. after putting AirPods in). The list
/// is re-read from the Mac each time the panel opens, so a device connected since is there.
struct MicPicker: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let mic = model.setting("input_device"), let options = mic.options, !options.isEmpty {
            HStack {
                Text("Microphone").lineLimit(1).fixedSize()
                Spacer(minLength: 12)
                Picker("Microphone", selection: model.binding(string: "input_device")) {
                    ForEach(options, id: \.value) { Text(Self.short($0.label)).tag($0.value) }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .frame(maxWidth: 190)
            }
            .onAppear { Task { await model.reloadSettings() } }
        }
    }

    /// "AIR 192 4 (2 ch)" → "AIR 192 4": the channel count means nothing here.
    static func short(_ label: String) -> String {
        label.replacingOccurrences(of: #" \(\d+ ch\)$"#, with: "", options: .regularExpression)
    }
}

/// The menu bar icon follows Vox's state: a waveform while it's listening, slashed when paused.
/// It deliberately does NOT change while Vox talks or types: those happen many times a minute, each
/// symbol has its own width, and every change moved the icon and the open panel anchored to it.
struct MenuBarIcon: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        let name = switch p.tone {
        case .paused: "mic.slash"
        case .off: "waveform.slash"
        case .problem: "exclamationmark.triangle"
        default: "waveform"
        }
        Image(systemName: name)
    }
}
