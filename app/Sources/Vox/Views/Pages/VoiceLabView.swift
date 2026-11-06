import AVFoundation
import SwiftUI

/// Voice Lab: record yourself saying test phrases so Vox can be measured against your real voice
/// and microphone, not synthetic ones. Each clip is transcribed by the engine and named after what
/// it heard. Vox stops listening while you record, so recording "Quit Vox" doesn't quit it.
struct VoiceLabView: View {
    @Environment(AppModel.self) private var model
    @State private var samples: [VoiceSample] = []
    @State private var prompts: [VoicePrompt] = []
    @State private var recorder = SampleRecorder()
    @State private var activePrompt: VoicePrompt?
    @State private var lastResult: VoiceSample?
    @State private var error: String?
    @State private var player: AVAudioPlayer?
    @State private var loaded = false

    var body: some View {
        RequiresEngine {
            PageScroll {
                intro
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout)
                }
                if !loaded {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                } else {
                    ForEach(categories, id: \.self) { cat in
                        SectionLabel(Self.title(for: cat))
                        Card(padding: 0) {
                            VStack(spacing: 0) {
                                let rows = prompts.filter { $0.category == cat }
                                ForEach(Array(rows.enumerated()), id: \.element.id) { i, p in
                                    promptRow(p)
                                    if i < rows.count - 1 { Divider().padding(.leading, Metrics.gap) }
                                }
                            }
                        }
                    }
                    SectionLabel("Your recordings (\(samples.count))")
                    if samples.isEmpty {
                        Text("Nothing recorded yet.").foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity).padding(.vertical, 20)
                    } else {
                        Card(padding: 0) {
                            VStack(spacing: 0) {
                                ForEach(Array(samples.enumerated()), id: \.element.id) { i, s in
                                    sampleRow(s)
                                    if i < samples.count - 1 { Divider().padding(.leading, Metrics.gap) }
                                }
                            }
                        }
                    }
                }
            }
            .toolbar {
                ToolbarItem {
                    Button {
                        toggle(VoicePrompt(category: "free", text: "", why: ""))
                    } label: {
                        Label("Record Anything", systemImage: "record.circle")
                    }
                    .help("Record any phrase. It's named from what Vox hears.")
                    .disabled(recorder.isRecording && activePrompt?.category != "free")
                }
            }
            .task { await load() }
            .onChange(of: recorder.elapsed) { _, t in
                if t > 20 && recorder.isRecording { Task { await finish() } }   // safety cap, still saved
            }
        }
    }

    private var categories: [String] {
        var seen: [String] = []
        for p in prompts where !seen.contains(p.category) { seen.append(p.category) }
        return seen
    }

    private var intro: some View {
        Card {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "waveform.badge.mic").font(.title).foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Teach Vox your voice").font(.headline)
                    Text("Record a few of these so changes to listening can be tested on how you actually speak. Click a phrase's record button, say it, then click stop. Vox stops listening while you record.")
                        .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private func promptRow(_ p: VoicePrompt) -> some View {
        let count = samples.filter { $0.prompt == p.text }.count
        let recordingThis = recorder.isRecording && activePrompt == p
        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("\u{201C}\(p.text)\u{201D}")
                Text(p.why).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if recordingThis {
                LevelMeter(level: recorder.level).frame(width: 60, height: 6)
                Text(String(format: "%.1f s", recorder.elapsed)).font(.callout.monospacedDigit()).foregroundStyle(.secondary)
            } else if count > 0 {
                Label("\(count)", systemImage: "checkmark.circle.fill").labelStyle(.titleAndIcon)
                    .font(.callout).foregroundStyle(.green)
            }
            recordButton(recordingThis) { toggle(p) }
                .disabled(recorder.isRecording && !recordingThis)
        }
        .padding(.horizontal, Metrics.gap).padding(.vertical, 10)
    }

    private func recordButton(_ recording: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: recording ? "stop.circle.fill" : "record.circle")
                .font(.title2)
                .foregroundStyle(recording ? Color.red : Color.secondary)
                .contentTransition(.symbolEffect(.replace))
        }
        .buttonStyle(.plain)
        .help(recording ? "Stop and save" : "Record")
    }

    private func sampleRow(_ s: VoiceSample) -> some View {
        HStack(spacing: 12) {
            Button { play(s) } label: { Image(systemName: "play.circle").font(.title3) }
                .buttonStyle(.plain).foregroundStyle(Color.accentColor).help("Play")
            VStack(alignment: .leading, spacing: 2) {
                Text(s.transcript.isEmpty ? "(Vox heard nothing)" : "\u{201C}\(s.transcript)\u{201D}")
                    .foregroundStyle(s.transcript.isEmpty ? .secondary : .primary)
                Text([s.prompt.isEmpty ? nil : "Asked: \(s.prompt)", String(format: "%.1f s", Double(s.durationMs) / 1000)]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if lastResult?.id == s.id { Text("New").font(.caption2.weight(.semibold)).foregroundStyle(.white)
                .padding(.horizontal, 6).padding(.vertical, 2).background(Color.accentColor, in: Capsule()) }
            Button(role: .destructive) { Task { await delete(s) } } label: { Image(systemName: "trash") }
                .buttonStyle(.borderless).foregroundStyle(.secondary).help("Delete this recording")
        }
        .padding(.horizontal, Metrics.gap).padding(.vertical, 10)
        .contextMenu { Button("Delete", role: .destructive) { Task { await delete(s) } } }
    }

    // MARK: Actions

    private func load() async {
        do {
            let r: VoiceLabList = try await model.api.get("samples")
            samples = r.samples; prompts = r.prompts; error = nil
        } catch { self.error = error.localizedDescription }
        loaded = true
    }

    private func toggle(_ p: VoicePrompt) {
        if recorder.isRecording {
            Task { await finish() }
        } else {
            Task { await begin(p) }
        }
    }

    private func begin(_ p: VoicePrompt) async {
        error = nil
        let wasPaused = model.isPaused
        recorder.restorePaused = wasPaused
        try? await model.api.setPaused(true)   // don't let Vox act on "quit vox" mid-recording
        do {
            try recorder.start()
            activePrompt = p
        } catch {
            self.error = "Couldn't start recording: \(error.localizedDescription)"
            if !wasPaused { try? await model.api.setPaused(false) }
        }
    }

    private func finish() async {
        let p = activePrompt
        let wav = recorder.stop()
        activePrompt = nil
        if !recorder.restorePaused { try? await model.api.setPaused(false) }
        guard let wav, let p else { return }
        do {
            let s: VoiceSample = try await model.api.send("samples", method: "POST", body: [
                "audio": wav.base64EncodedString(), "prompt": p.text, "category": p.category,
            ])
            lastResult = s
            samples.insert(s, at: 0)
        } catch { self.error = error.localizedDescription }
    }

    private func play(_ s: VoiceSample) {
        Task {
            var req = URLRequest(url: URL(string: "http://127.0.0.1:\(model.api.port)/api/samples/\(s.id)/audio")!)
            req.timeoutInterval = 5
            guard let (data, _) = try? await URLSession.shared.data(for: req) else { return }
            player = try? AVAudioPlayer(data: data)
            player?.play()
        }
    }

    private func delete(_ s: VoiceSample) async {
        samples.removeAll { $0.id == s.id }
        do { try await model.api.delete("samples/\(s.id)") } catch { await load() }
    }

    static func title(for category: String) -> String {
        switch category {
        case "wake": "Waking Vox"
        case "command": "Commands"
        case "unfinished": "Stopping mid-sentence"
        case "finished": "Finished sentences"
        case "ambient": "Talking to someone else"
        case "dictation": "Dictation"
        default: category.capitalized
        }
    }
}

private struct LevelMeter: View {
    var level: Float
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(.quaternary)
                Capsule().fill(Color.red.gradient).frame(width: g.size.width * CGFloat(max(0.05, min(1, level))))
            }
        }
        .animation(.linear(duration: 0.1), value: level)
    }
}

/// Records 16 kHz mono 16-bit WAV, the format the engine's models use, with a live level.
@MainActor
@Observable
final class SampleRecorder {
    private(set) var isRecording = false
    private(set) var level: Float = 0
    private(set) var elapsed: Double = 0
    var restorePaused = false
    private var recorder: AVAudioRecorder?
    private var timer: Timer?
    private let url = FileManager.default.temporaryDirectory.appending(path: "vox-voice-lab.wav")

    func start() throws {
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
        ]
        let r = try AVAudioRecorder(url: url, settings: settings)
        r.isMeteringEnabled = true
        guard r.record() else { throw NSError(domain: "Vox", code: 1, userInfo: [NSLocalizedDescriptionKey: "the microphone isn't available"]) }
        recorder = r
        isRecording = true
        elapsed = 0
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let r = self.recorder else { return }
                r.updateMeters()
                self.level = pow(10, r.averagePower(forChannel: 0) / 40)   // dB → 0…1, roughly
                self.elapsed = r.currentTime
            }
        }
    }

    func stop() -> Data? {
        timer?.invalidate(); timer = nil
        recorder?.stop(); recorder = nil
        isRecording = false
        level = 0
        return try? Data(contentsOf: url)
    }
}

// MARK: Voice Lab wire types

struct VoicePrompt: Codable, Hashable, Identifiable {
    var category: String
    var text: String
    var why: String
    var id: String { category + "|" + text }
}

struct VoiceSample: Codable, Hashable, Identifiable {
    var id: String
    var file: String
    var transcript: String
    var prompt: String
    var category: String
    var durationMs: Int
    var created: String
}

struct VoiceLabList: Codable { var samples: [VoiceSample]; var prompts: [VoicePrompt] }
