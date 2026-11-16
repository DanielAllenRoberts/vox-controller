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
                                                       description: Text("What you say to Vox, and what it says back, appears here."))
                                    .padding(.top, 80)
                            }
                            ForEach(Array(model.turns.enumerated()), id: \.element.id) { i, turn in
                                if showsTime(at: i) {
                                    Text(turn.date?.formatted(date: .abbreviated, time: .shortened) ?? "")
                                        .font(.caption).foregroundStyle(.tertiary)
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

    /// A timestamp row before the first turn and after any gap of 10+ minutes.
    private func showsTime(at i: Int) -> Bool {
        guard i > 0, let a = model.turns[i - 1].date, let b = model.turns[i].date else { return i == 0 }
        return b.timeIntervalSince(a) > 600
    }
}

private struct Bubble: View {
    var turn: Turn
    @State private var expanded = false

    /// A pasted page of notes (~3,000 characters, 2026-11-11) froze the whole app: a row that tall in
    /// a bottom-anchored LazyVStack kept SwiftUI re-placing rows forever (100% CPU on the main thread,
    /// `LazySubviewPlacements` in the sample). Long turns start collapsed; "Show more" opens one.
    private var isLong: Bool { turn.text.count > 600 || turn.text.filter(\.isNewline).count > 10 }

    var body: some View {
        HStack {
            if turn.isUser { Spacer(minLength: 80) }
            VStack(alignment: .leading, spacing: 4) {
                Text(turn.text)
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
            .background(turn.isUser ? AnyShapeStyle(Color.accentColor.gradient) : AnyShapeStyle(.quaternary),
                        in: RoundedRectangle(cornerRadius: 17, style: .continuous))
            .help(turn.kind.map { "Handled as: \($0)" } ?? "")
            if !turn.isUser { Spacer(minLength: 80) }
        }
    }
}
