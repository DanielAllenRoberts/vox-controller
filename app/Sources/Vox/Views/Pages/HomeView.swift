import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        PageScroll {
            PermissionLagBanner()
            Hero()
            AskField()
            if model.engine.isRunning {
                HStack(alignment: .top, spacing: Metrics.gap) {
                    RecentCard().frame(maxWidth: .infinity)
                    VStack(spacing: Metrics.gap) {
                        MicCard()
                        QuickSettingsCard()
                        BrainsCard()
                    }
                    .frame(width: 280)
                }
                TipsCard()
            }
        }
    }
}

// MARK: Hero

private struct Hero: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        HStack(spacing: 18) {
            ZStack {
                Circle().fill(p.color.opacity(0.12)).frame(width: 64, height: 64)
                Image(systemName: p.symbol)
                    .font(.system(size: 26, weight: .medium))
                    .foregroundStyle(p.color)
                    .contentTransition(.symbolEffect(.replace))
            }
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(p.title).font(.largeTitle.weight(.semibold))
                    StatusOrb(presence: p, size: 10)
                }
                Text(p.detail).font(.title3).foregroundStyle(.secondary).lineLimit(2)
            }
            Spacer()
            HeroActions()
        }
        .padding(.vertical, 8)
        .animation(.smooth, value: p)
    }
}

private struct HeroActions: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        switch model.engine.state {
        case .running:
            Button {
                model.togglePaused()
            } label: {
                Label(model.isPaused ? "Resume" : "Pause", systemImage: model.isPaused ? "mic.fill" : "mic.slash")
            }
            .controlSize(.large)
            .help(model.isPaused ? "Start listening again" : "Stop listening to the microphone. Typing still works.")
        case .stopped, .failed:
            Button("Start Vox") { model.boot() }
                .buttonStyle(.borderedProminent).controlSize(.large)
        case .notInstalled:
            Button("Set Up Vox…") { NotificationCenter.default.post(name: .voxShowOnboarding, object: nil) }
                .buttonStyle(.borderedProminent).controlSize(.large)
        case .starting:
            ProgressView().controlSize(.small)
        }
    }
}

// MARK: Type to Vox

struct AskField: View {
    @Environment(AppModel.self) private var model
    @State private var text = ""
    @State private var error: String?
    @FocusState private var focused: Bool
    var compact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Image(systemName: "text.cursor").foregroundStyle(.secondary)
                TextField(compact ? "Type to Vox…" : "Type to Vox. Anything you'd say out loud", text: $text)
                    .textFieldStyle(.plain)
                    .font(compact ? .body : .title3)
                    .focused($focused)
                    .onSubmit(send)
                    .disabled(!model.engine.isRunning)
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: compact ? 20 : 24))
                }
                .buttonStyle(.plain)
                .foregroundStyle(text.isEmpty ? Color.secondary : Color.accentColor)
                .disabled(text.isEmpty || !model.engine.isRunning)
                .help("Send (Return)")
                .accessibilityLabel("Send to Vox")
                StopButton(size: compact ? 20 : 24)
            }
            .padding(.horizontal, 14).padding(.vertical, compact ? 8 : 12)
            .background(.background.secondary, in: Capsule())
            .overlay(Capsule().strokeBorder(focused ? Color.accentColor.opacity(0.6) : Color.secondary.opacity(0.2)))
            if let error {
                Text(error).font(.caption).foregroundStyle(.red).padding(.leading, 14)
            }
        }
    }

    /// Return is handled by the field's onSubmit only; a second Return shortcut on the button fought
    /// other default buttons (Setup's Continue). The text is cleared only once Vox has it, so a
    /// failed send doesn't throw away what was typed.
    private func send() {
        let t = text
        guard !t.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        Task {
            error = await model.say(t)
            if error == nil, text == t { text = "" }
        }
    }
}

/// ⏹ Stops whatever Vox is doing right now: the reply it's speaking, a request it's thinking
/// about, an agent task. Listening carries on. ⌘. does the same, as it does across the Mac.
struct StopButton: View {
    @Environment(AppModel.self) private var model
    var size: CGFloat = 20
    @State private var result: String?

    var body: some View {
        Button(action: stop) {
            Image(systemName: "stop.circle.fill").font(.system(size: size))
        }
        .buttonStyle(.plain)
        .foregroundStyle(result == nil ? Color.secondary : Color.red)
        .disabled(!model.engine.isRunning)
        .keyboardShortcut(".", modifiers: .command)
        .help(result ?? "Stop what Vox is doing: speaking, thinking or an agent task (⌘.)")
        .accessibilityLabel("Stop Vox")
    }

    private func stop() {
        Task {
            let stopped = await model.stopNow()
            result = switch stopped {
            case nil: "Couldn't reach Vox"
            case let s? where s.isEmpty: "Stopped (nothing was running)"
            case let s?: "Stopped " + s.joined(separator: " and ")
            }
            try? await Task.sleep(for: .seconds(1.5))
            result = nil
        }
    }
}

// MARK: Cards

private struct RecentCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Recent").font(.headline)
                    Spacer()
                    Button("Show All") { model.page = .conversation }.buttonStyle(.link)
                }
                let recent = Array(model.turns.suffix(6))
                if recent.isEmpty {
                    Text("Nothing yet. Say \"Hey Vox\" or type above.")
                        .foregroundStyle(.secondary).padding(.vertical, 20).frame(maxWidth: .infinity)
                } else {
                    ForEach(recent) { t in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Image(systemName: t.isUser ? "person.fill" : "waveform")
                                .font(.caption).foregroundStyle(t.isUser ? Color.secondary : Color.accentColor)
                                .frame(width: 14)
                            Text(t.text).lineLimit(2).foregroundStyle(t.isUser ? .primary : .secondary)
                            Spacer(minLength: 4)
                            Text(t.date?.friendly ?? "").font(.caption).foregroundStyle(.tertiary)
                        }
                    }
                }
            }
        }
    }
}

/// What the microphone is hearing right now, and which microphone it is: the first thing to check
/// when Vox seems not to respond.
private struct MicCard: View {
    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                Text("Microphone").font(.headline)
                MicLevelMeter()
                MicPicker()
            }
        }
    }
}

private struct QuickSettingsCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                Text("Quick Settings").font(.headline)
                SwitchRow("Speak replies", isOn: model.binding(bool: "tts_enabled"))
                SwitchRow("Learn new commands", isOn: Binding(
                    get: { model.value("learning_mode").string != "off" },
                    set: { on in
                        // Turning it back on restores whichever mode it was in (auto / suggest),
                        // rather than silently promoting "suggest" to "auto".
                        let current = model.value("learning_mode").string
                        if on {
                            model.set("learning_mode", .string(UserDefaults.standard.string(forKey: "lastLearningMode") ?? "auto"))
                        } else {
                            if current != "off" { UserDefaults.standard.set(current, forKey: "lastLearningMode") }
                            model.set("learning_mode", .string("off"))
                        }
                    }))
                SwitchRow("Look at the screen", isOn: model.binding(bool: "screen_vision_enabled"))
            }
        }
    }
}

private struct BrainsCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Brains").font(.headline)
                    Spacer()
                    SettingsLink { Text("Change…") }.buttonStyle(.link)
                }
                if let s = model.engine.status {
                    BrainRow(title: "Quick replies", ref: s.smallBrain, symbol: "bolt.fill")
                    BrainRow(title: "Hard questions", ref: s.bigBrain, symbol: "sparkles")
                }
            }
        }
    }
}

private struct BrainRow: View {
    var title: String
    var ref: BrainRef
    var symbol: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol).foregroundStyle(.secondary).frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(BrainNames.model(ref.model)).font(.callout)
                Text("\(title) · \(BrainNames.provider(ref.provider, model: ref.model))")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

private struct TipsCard: View {
    private let tips: [(String, String)] = [
        ("Hold Right ⌥ and speak", "Talk without a wake word; let go to send"),
        ("Take control", "Start giving commands"),
        ("Hey Vox", "Ask a question or have a chat"),
        ("Vox, open Safari", "One command without switching modes"),
        ("Start typing", "Dictate into any text field"),
        ("Show clickable", "Number everything you can click"),
        ("Point at the export button", "Vox circles it on screen"),
    ]

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                Text("Try Saying").font(.headline)
                LazyVGrid(columns: [GridItem(.flexible(), alignment: .topLeading), GridItem(.flexible(), alignment: .topLeading)],
                          alignment: .leading, spacing: 12) {
                    ForEach(tips, id: \.0) { phrase, what in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\u{201C}\(phrase)\u{201D}").font(.callout.weight(.medium))
                            Text(what).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }
}
