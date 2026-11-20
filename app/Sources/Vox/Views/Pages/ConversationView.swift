import SwiftUI

struct ConversationView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        RequiresEngine {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 6) {
                            if model.turns.isEmpty {
                                ContentUnavailableView("No conversation yet", systemImage: "bubble.left.and.bubble.right",
                                                       description: Text("What you say, what Vox says back, and anything your agents report appears here — each labelled with who said it."))
                                    .padding(.top, 80)
                            }
                            ForEach(Array(model.turns.enumerated()), id: \.element.id) { i, turn in
                                if showsHeader(at: i) {
                                    SpeakerHeader(turn: turn)
                                        .padding(.top, i == 0 ? 0 : 14).padding(.bottom, 2)
                                }
                                Bubble(turn: turn).id(turn.id)
                            }
                        }
                        .padding(.horizontal, Metrics.page).padding(.vertical, 18)
                        .frame(maxWidth: 820)
                        .frame(maxWidth: .infinity)
                    }
                    .defaultScrollAnchor(.bottom)
                    .onChange(of: model.turns.last?.id) { _, id in
                        if let id { withAnimation(.smooth) { proxy.scrollTo(id, anchor: .bottom) } }
                    }
                }
                AskField(compact: true)
                    .padding(.horizontal, Metrics.page).padding(.vertical, 12)
                    .frame(maxWidth: 820)
                    .frame(maxWidth: .infinity)
                    .background(.bar)
            }
        }
    }

    /// A source+time header before the first turn, whenever the speaker changes, and after a 10+
    /// minute gap — so every run of messages is labelled with who said it and when.
    private func showsHeader(at i: Int) -> Bool {
        guard i > 0 else { return true }
        let prev = model.turns[i - 1], cur = model.turns[i]
        if prev.speaker != cur.speaker { return true }
        guard let a = prev.date, let b = cur.date else { return false }
        return b.timeIntervalSince(a) > 600
    }
}

/// "You" / "Vox" / an agent's name, with the time, aligned to the bubble it heads.
private struct SpeakerHeader: View {
    var turn: Turn

    var body: some View {
        HStack(spacing: 6) {
            if turn.isUser { Spacer(minLength: 0) }
            if turn.isAgent {
                Image(systemName: "cpu").font(.caption2)
                    .foregroundStyle(Color.orange)
            }
            Text(turn.sourceLabel)
                .font(.caption.weight(.semibold))
                .foregroundStyle(turn.isAgent ? Color.orange : .secondary)
            if let d = turn.date {
                Text(d.formatted(date: .omitted, time: .shortened))
                    .font(.caption).foregroundStyle(.tertiary)
            }
            if !turn.isUser { Spacer(minLength: 0) }
        }
    }
}

private struct Bubble: View {
    var turn: Turn
    @State private var expanded = false

    /// A pasted page of notes (~3,000 characters, 2026-11-11) froze the whole app: a row that tall in
    /// a bottom-anchored LazyVStack kept SwiftUI re-placing rows forever (100% CPU on the main thread,
    /// `LazySubviewPlacements` in the sample). Long turns start collapsed; "Show more" opens one.
    private var isLong: Bool { turn.text.count > 600 || turn.text.filter(\.isNewline).count > 10 }

    private var background: AnyShapeStyle {
        if turn.isUser { return AnyShapeStyle(Color.accentColor.gradient) }
        if turn.isAgent { return AnyShapeStyle(Color.orange.opacity(0.16)) }
        return AnyShapeStyle(.quaternary)
    }

    var body: some View {
        HStack {
            if turn.isUser { Spacer(minLength: 80) }
            VStack(alignment: .leading, spacing: 4) {
                Text(turn.displayText)
                    .lineLimit(isLong && !expanded ? 8 : nil)
                    .textSelection(.enabled)
                if isLong {
                    Button(expanded ? "Show less" : "Show more") { expanded.toggle() }
                        .buttonStyle(.plain).font(.caption.weight(.semibold))
                        .foregroundStyle(turn.isUser ? Color.white.opacity(0.85) : Color.accentColor)
                }
            }
            .padding(.horizontal, 13).padding(.vertical, 8)
            .foregroundStyle(turn.isUser ? Color.white : Color.primary)
            .background(background, in: RoundedRectangle(cornerRadius: 17, style: .continuous))
            .help(helpText)
            if !turn.isUser { Spacer(minLength: 80) }
        }
    }

    /// Exact time (and how it was handled) on hover, so every single message is timestamped.
    private var helpText: String {
        var parts: [String] = []
        if let d = turn.date { parts.append(d.formatted(date: .abbreviated, time: .standard)) }
        if let k = turn.kind, k != "agent" { parts.append("Handled as: \(k)") }
        return parts.joined(separator: "\n")
    }
}
