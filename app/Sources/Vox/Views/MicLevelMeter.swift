import SwiftUI

/// A live bar showing how loud the microphone Vox has open is, so you can see Vox hears you before
/// you rely on it. Reads the engine's /mic/level about twelve times a second while on screen. The
/// tick marks the speech threshold: sound past it is what Vox treats as someone talking.
struct MicLevelMeter: View {
    @Environment(AppModel.self) private var model
    /// Fixed reading for `--snapshot`, where no engine is polled.
    var preview: MicLevel?
    /// Set once the level has crossed the speech threshold while this meter was on screen.
    var heardSpeech: Binding<Bool>?

    @State private var reading = MicLevel(live: false, level: 0, threshold: 0.3)
    @State private var shown: Double = 0
    @State private var peak: Double = 0
    /// Last time the level crossed the threshold. The caption holds "can hear you" briefly after,
    /// or it flickered between captions with every rise and fall of a voice.
    @State private var lastSpeech = Date.distantPast

    var body: some View {
        let r = preview ?? reading
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { geo in
                let w = geo.size.width
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.15))
                    Capsule()
                        .fill(LinearGradient(colors: [.green, r.level >= r.threshold ? .green : .mint],
                                             startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(8, w * (preview?.level ?? shown)))
                        .opacity(r.live ? 1 : 0)
                    Rectangle().fill(Color.primary.opacity(0.18))
                        .frame(width: 2).offset(x: w * (preview?.level ?? peak) - 1)
                        .opacity(r.live && peak > 0.02 ? 1 : 0)
                    Rectangle().fill(Color.primary.opacity(0.45))
                        .frame(width: 2, height: 18).offset(x: w * r.threshold - 1)
                }
            }
            .frame(height: 12)
            .accessibilityElement()
            .accessibilityLabel("Microphone level")
            .accessibilityValue(caption(r))
            Label(caption(r), systemImage: icon(r))
                .font(.callout).foregroundStyle(color(r))
        }
        .task(id: preview == nil) {
            guard preview == nil else { return }
            while !Task.isCancelled {
                if let next: MicLevel = try? await model.api.get("mic/level") {
                    reading = next
                    // Rise fast, fall gently, like a VU meter, so a word reads as a swell, not a flicker.
                    shown = next.level > shown ? next.level : max(next.level, shown - 0.06)
                    peak = next.level > peak ? next.level : max(0, peak - 0.012)
                    if next.live && next.level >= next.threshold {
                        lastSpeech = Date()
                        heardSpeech?.wrappedValue = true
                    }
                } else {
                    reading.live = false
                }
                try? await Task.sleep(for: .milliseconds(80))
            }
        }
        .animation(.linear(duration: 0.08), value: shown)
    }

    private func hearing(_ r: MicLevel) -> Bool {
        r.live && (r.level >= r.threshold || Date().timeIntervalSince(lastSpeech) < 1.5)
    }

    private func caption(_ r: MicLevel) -> String {
        if !r.live { return model.engine.isRunning ? "No sound is reaching Vox. Check the microphone below." : "Waiting for Vox to start…" }
        if hearing(r) { return "Vox can hear you" }
        return "Listening. Say something…"
    }

    private func icon(_ r: MicLevel) -> String {
        if !r.live { return "mic.slash" }
        return hearing(r) ? "checkmark.circle.fill" : "mic"
    }

    private func color(_ r: MicLevel) -> Color {
        if !r.live { return model.engine.isRunning ? .orange : .secondary }
        return hearing(r) ? .green : .secondary
    }
}

struct MicLevel: Decodable, Equatable {
    var live: Bool
    var level: Double
    var threshold: Double
}
