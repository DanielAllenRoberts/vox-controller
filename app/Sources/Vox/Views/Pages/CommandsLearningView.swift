import SwiftUI

/// The Learning tab of Commands: what Vox taught itself, and what it's suggesting.
struct LearningReview: View {
    var store: CommandsStore
    var search: String

    @Environment(AppModel.self) private var model
    @State private var showRejected = false
    @State private var confirm: Confirm?

    /// Destructive actions wait for a yes.
    private enum Confirm: Identifiable {
        case forget(LearnedCommand), unalias(LearnedAlias)
        var id: String {
            switch self {
            case .forget(let c): "c\(c.id)"
            case .unalias(let a): "a\(a.id)"
            }
        }
    }

    private var query: String { search.trimmingCharacters(in: .whitespaces).lowercased() }

    private func hit(_ texts: [String]) -> Bool {
        query.isEmpty || texts.contains { $0.lowercased().contains(query) }
    }

    var body: some View {
        let l = store.learning
        // Search what the rows show, not the raw labels and context names behind them.
        let suggestions = store.suggestions.filter {
            hit($0.phrases + [CommandWords.describe($0.intent, $0.arg), CommandWords.place($0.context)])
        }
        let learned = l.learned.filter {
            hit($0.phrases + [CommandWords.title(label: $0.label, intent: $0.intent, arg: $0.arg), CommandWords.place($0.context)])
        }
        let aliases = (l.aliases ?? []).filter { hit([$0.text, $0.label]) }
        let rejected = l.candidates.filter { $0.blocked && hit($0.phrases + [CommandWords.describe($0.intent, $0.arg)]) }
        let nothing = suggestions.isEmpty && learned.isEmpty && aliases.isEmpty && rejected.isEmpty

        Form {
            if query.isEmpty { modeSection }

            if nothing {
                Section {
                    Group {
                        if query.isEmpty {
                            ContentUnavailableView("Nothing learned yet", systemImage: "sparkles",
                                                   description: Text("When Vox has to work out a command for you, it shows up here. Repeat it and Vox saves it, so next time it's instant."))
                        } else {
                            ContentUnavailableView.search(text: search)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
            }

            if !learned.isEmpty {
                Section {
                    ForEach(learned) { c in
                        LearnedRow(command: c) { confirm = .forget(c) }
                    }
                } header: {
                    Text("Learned Commands").pageSectionHeader()
                } footer: {
                    Text("These work now. New ones are on trial: if you don't use them enough, Vox lets them go on its own.")
                        .foregroundStyle(.secondary)
                }
            }

            if !aliases.isEmpty {
                Section {
                    ForEach(aliases) { a in
                        AliasRow(alias: a) { confirm = .unalias(a) }
                    }
                } header: {
                    Text("New Ways to Say Things").pageSectionHeader()
                } footer: {
                    Text("Vox already knew how to do these, so it added your wording to the existing command. These work now.")
                        .foregroundStyle(.secondary)
                }
            }

            if !suggestions.isEmpty {
                Section {
                    ForEach(suggestions) { c in
                        SuggestionRow(candidate: c, onApprove: { store.approve(c) }, onReject: { store.reject(c) })
                    }
                } header: {
                    Text("Suggestions").pageSectionHeader()
                } footer: {
                    Text("Suggestions don't do anything yet. Approve one and it becomes a command. Reject it and Vox won't suggest it again.")
                        .foregroundStyle(.secondary)
                }
            }

            if !rejected.isEmpty {
                Section {
                    DisclosureGroup(isExpanded: $showRejected) {
                        ForEach(rejected) { c in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(CommandWords.describe(c.intent, c.arg))
                                Text(CommandWords.quoted(c.phrases)).font(.callout).lineLimit(2)
                            }
                            .foregroundStyle(.secondary)
                        }
                    } label: {
                        Text(rejected.count == 1 ? "1 rejected suggestion" : "\(rejected.count) rejected suggestions")
                    }
                }
            }
        }
        .formStyle(.grouped)
        .animation(.smooth, value: store.learning.candidates)
        .animation(.smooth, value: store.learning.learned)
        .confirmationDialog(confirmTitle, isPresented: confirmBinding, titleVisibility: .visible, presenting: confirm) { c in
            switch c {
            case .forget(let cmd):
                Button("Forget Command", role: .destructive) { store.forget(cmd.id) }
            case .unalias(let a):
                Button("Remove Phrase", role: .destructive) { store.removePhrase(a.id, from: a.command_id) }
            }
        } message: { c in
            switch c {
            case .forget: Text("Vox will stop using it, and won't learn it again for a while.")
            case .unalias(let a): Text("Saying it will no longer \(a.label.lowercased()).")
            }
        }
    }

    private var modeSection: some View {
        Section {
            Picker("Learn new commands", selection: model.binding(string: "learning_mode")) {
                Text("Automatically").tag("auto")
                Text("Suggest only").tag("suggest")
                Text("Off").tag("off")
            }
        } footer: {
            Text(modeFooter).foregroundStyle(.secondary)
        }
    }

    private var modeFooter: String {
        let hits = Int(model.value("learning_min_hits").number ?? 1)
        let days = Int(model.value("learning_window_days").number ?? 10)
        let when = hits <= 1 ? "When Vox works out a command for you"
            : "When Vox works out the same command \(hits == 2 ? "twice" : "\(hits) times") within \(days) days"
        switch model.value("learning_mode").string {
        case "off": return "Vox won't learn anything new. What it already learned keeps working."
        case "suggest": return "\(when), it suggests saving it here. Nothing is saved until you approve it."
        default: return "\(when), it remembers how, so it's instant next time."
        }
    }

    private var confirmTitle: String {
        switch confirm {
        case .forget(let c): "Forget \u{201C}\(CommandWords.title(label: c.label, intent: c.intent, arg: c.arg))\u{201D}?"
        case .unalias(let a): "Remove \u{201C}\(a.text)\u{201D}?"
        case nil: ""
        }
    }

    private var confirmBinding: Binding<Bool> {
        Binding(get: { confirm != nil }, set: { if !$0 { confirm = nil } })
    }
}

// MARK: Rows

private struct SuggestionRow: View {
    var candidate: LearningCandidate
    var onApprove: () -> Void
    var onReject: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(CommandWords.describe(candidate.intent, candidate.arg))
                    Text(CommandWords.place(candidate.context)).foregroundStyle(.secondary)
                }
                Text(CommandWords.quoted(candidate.phrases))
                    .font(.callout).foregroundStyle(.secondary).lineLimit(2)
                Text(meta).font(.caption).foregroundStyle(.tertiary)
            }
            Spacer(minLength: 12)
            Button("Reject", action: onReject).help("Don't suggest this again")
            Button("Approve", action: onApprove).help("Save this as a command")
        }
        .padding(.vertical, 2)
        .help(candidate.intent)
    }

    private var meta: String {
        var parts = [candidate.hits == 1 ? "Heard once" : "Heard \(candidate.hits) times"]
        if let d = ISO8601.parseUTC(candidate.last_seen) { parts.append("last " + d.friendlyInline) }
        if candidate.negatives > 0 { parts.append(candidate.negatives == 1 ? "corrected once" : "corrected \(candidate.negatives) times") }
        return parts.joined(separator: " · ")
    }
}

private struct LearnedRow: View {
    var command: LearnedCommand
    var onForget: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(CommandWords.title(label: command.label, intent: command.intent, arg: command.arg))
                    Text(CommandWords.place(command.context)).foregroundStyle(.secondary)
                }
                Text(CommandWords.quoted(command.phrases))
                    .font(.callout).foregroundStyle(.secondary).lineLimit(2)
                Text(meta).font(.caption).foregroundStyle(.tertiary)
            }
            .opacity(command.enabled ? 1 : 0.55)
            Spacer(minLength: 12)
            HoverDeleteButton(visible: hovering, help: "Forget This Command", action: onForget)
            status
        }
        .padding(.vertical, 2)
        .onHover { hovering = $0 }
        .help(command.intent)
        .contextMenu { Button("Forget This Command…", role: .destructive, action: onForget) }
    }

    @ViewBuilder private var status: some View {
        if command.probation {
            Label("On trial", systemImage: "hourglass")
                .font(.callout).foregroundStyle(.orange)
                .help(trialHelp)
        } else {
            Label("Kept", systemImage: "checkmark.circle.fill")
                .font(.callout).foregroundStyle(.green)
                .help("Used enough to keep for good")
        }
    }

    private var trialHelp: String {
        let uses = command.probation_uses_left ?? 0
        let usesText = uses == 1 ? "1 more use" : "\(uses) more uses"
        if let days = command.probation_days_left {
            return "Needs \(usesText) in the next \(days == 1 ? "day" : "\(days) days") to be kept"
        }
        return "Needs \(usesText) to be kept"
    }

    private var meta: String {
        var parts = [command.hits == 1 ? "Used once" : command.hits == 0 ? "Not used yet" : "Used \(command.hits) times"]
        if let d = ISO8601.parseUTC(command.last_used_at) { parts.append("last " + d.friendlyInline) }
        else if let d = ISO8601.parseUTC(command.learned_at) { parts.append("learned " + d.friendlyInline) }
        if command.probation { parts.append(trialHelp.prefix(1).lowercased() + trialHelp.dropFirst()) }
        if !command.enabled { parts.append("turned off") }
        return parts.joined(separator: " · ")
    }
}

private struct AliasRow: View {
    var alias: LearnedAlias
    var onRemove: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 10) {
            Text("\u{201C}\(alias.text)\u{201D}")
            Image(systemName: "arrow.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
            Text(alias.label).foregroundStyle(.secondary)
            Spacer(minLength: 12)
            HoverDeleteButton(visible: hovering, help: "Remove This Phrase", action: onRemove)
            Text(alias.hits == 1 ? "Used once" : "Used \(alias.hits) times").font(.caption).foregroundStyle(.tertiary)
        }
        .onHover { hovering = $0 }
        .contextMenu { Button("Remove This Phrase…", role: .destructive, action: onRemove) }
    }
}

private extension Date {
    /// `friendly` for use mid-sentence: "last just now", "last yesterday 14:02", "last 3 Nov".
    var friendlyInline: String { friendly.prefix(1).lowercased() + friendly.dropFirst() }
}
