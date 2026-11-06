import SwiftUI

/// A kanban board: lists side by side, cards with deadlines, tags and checklists. ⌘-click picks
/// several cards to move, archive or delete together. Vox and its agents read and write the same
/// board, so it doubles as a shared to-do list; a deadline also sets a reminder.
struct BoardView: View {
    @Environment(AppModel.self) private var model
    @State private var board: Board?
    @State private var error: String?
    @State private var loadError: String?
    @State private var editing: BoardCard?
    @State private var deleting: [BoardCard] = []
    @State private var addingList = false
    @State private var newListName = ""
    @State private var selection: Set<Int> = []
    @State private var showArchived = false
    @State private var search = ""

    var body: some View {
        RequiresEngine {
            content
                .safeAreaInset(edge: .bottom) {
                    if !selection.isEmpty, let board {
                        SelectionBar(count: selection.count, lists: board.lists, archived: showArchived,
                                     onMove: { l in Task { await bulk(selected.map { BoardOp(op: "move", card: $0.id, toList: l.id) }, "Couldn't move those cards.") } },
                                     onArchive: { Task { await bulk(selected.map { BoardOp(op: "archive", card: $0.id, archived: !showArchived) }, "Couldn't archive those cards.") } },
                                     onDelete: { deleting = selected },
                                     onDone: { selection = [] })
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
                .animation(.smooth(duration: 0.2), value: selection.isEmpty)
                .pageErrors($error, loadError: $loadError, loaded: board != nil)
                .refreshesPage(load)
                .searchable(text: $search, prompt: "Search cards")
                .toolbar {
                    ToolbarItem {
                        Toggle(isOn: $showArchived) { Label("Archived", systemImage: "archivebox") }
                            .toggleStyle(.button)
                            .help(showArchived ? "Back to the board" : "Show archived cards")
                    }
                    ToolbarItem(placement: .primaryAction) {
                        Button("Add List", systemImage: "plus") { newListName = ""; addingList = true }
                            .help("Add a list")
                            .disabled(showArchived)
                    }
                }
                .onChange(of: showArchived) { _, _ in selection = []; Task { await load() } }
                .sheet(item: $editing) { card in
                    CardEditor(card: card) { draft in
                        Task { await save(card, draft) }
                    } onArchive: {
                        Task { await bulk([BoardOp(op: "archive", card: card.id, archived: !card.isArchived)], "Couldn't archive that card.") }
                    } onDelete: {
                        deleting = [card]
                    }
                }
                .confirmationDialog(deleteTitle, isPresented: .init(get: { !deleting.isEmpty }, set: { if !$0 { deleting = [] } }),
                                    titleVisibility: .visible) {
                    Button(deleting.count == 1 ? "Delete Card" : "Delete \(deleting.count) Cards", role: .destructive) {
                        let cards = deleting
                        Task { await bulk(cards.map { BoardOp(op: "delete", card: $0.id) }, "Couldn't delete that.") }
                    }
                } message: {
                    Text("This can't be undone. Archiving keeps a card out of the way without losing it.")
                }
                .alert("New List", isPresented: $addingList) {
                    TextField("Name", text: $newListName)
                    Button("Add") { Task { await addList(newListName) } }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text("Give the list a short name, like \u{201C}Waiting\u{201D}.")
                }
        }
    }

    private var selected: [BoardCard] { (board?.lists ?? []).flatMap(\.cards).filter { selection.contains($0.id) } }

    private var deleteTitle: String {
        deleting.count == 1 ? "Delete \u{201C}\(deleting[0].title)\u{201D}?" : "Delete \(deleting.count) cards?"
    }

    private var query: String { search.trimmingCharacters(in: .whitespaces).lowercased() }

    private func matches(_ c: BoardCard) -> Bool {
        query.isEmpty || c.title.lowercased().contains(query) || c.body.lowercased().contains(query)
            || c.tags.contains { $0.lowercased().contains(query) }
    }

    @ViewBuilder
    private var content: some View {
        if let board {
            let cards = board.lists.flatMap(\.cards)
            if board.lists.isEmpty {
                ContentUnavailableView {
                    Label("No lists yet", systemImage: "rectangle.split.3x1")
                } description: {
                    Text("Add a list, then add cards to it. Vox can read and update this board too.")
                } actions: {
                    Button("Add List") { newListName = ""; addingList = true }
                }
            } else if showArchived && cards.isEmpty {
                ContentUnavailableView("Nothing archived", systemImage: "archivebox",
                                       description: Text("Archived cards wait here. Right-click a card and choose Archive to put one away."))
            } else if !query.isEmpty && !cards.contains(where: matches) {
                ContentUnavailableView.search(text: search)
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    if !showArchived { DueSummary(cards: cards).padding(.horizontal, Metrics.page).padding(.top, Metrics.gap) }
                    ScrollView(.horizontal) {
                        HStack(alignment: .top, spacing: Metrics.gap) {
                            ForEach(board.lists) { list in
                                ListColumn(list: list, cards: list.cards.filter(matches),
                                           others: board.lists.filter { $0.id != list.id },
                                           archived: showArchived, selection: selection,
                                           onTap: tap,
                                           onSelect: toggle,
                                           onArchive: { c in Task { await bulk([BoardOp(op: "archive", card: c.id, archived: !c.isArchived)], "Couldn't archive that card.") } },
                                           onDelete: { deleting = [$0] },
                                           onAdd: { text in Task { await addCards(text, to: list) } },
                                           onMove: { id, listId, before in Task { await move(id, to: listId, before: before) } })
                            }
                        }
                        .padding(Metrics.page)
                        .frame(maxHeight: .infinity, alignment: .top)
                    }
                }
            }
        } else if let loadError {
            LoadErrorView(title: "Couldn't load the board", message: loadError) { Task { await load() } }
        } else {
            PageLoading()
        }
    }

    /// A plain click opens the card; ⌘-click (or any click while cards are selected) selects.
    private func tap(_ card: BoardCard) {
        if NSEvent.modifierFlags.contains(.command) || !selection.isEmpty { toggle(card) }
        else { editing = card }
    }

    private func toggle(_ card: BoardCard) {
        if selection.contains(card.id) { selection.remove(card.id) } else { selection.insert(card.id) }
    }

    // MARK: Data

    private func load() async {
        do {
            board = try await model.api.get(showArchived ? "board?archived=true" : "board")
            selection.formIntersection(Set((board?.lists ?? []).flatMap(\.cards).map(\.id)))
            loadError = nil
        } catch { loadError = ErrorWords.reason(error) }
    }

    /// Runs a change against the engine, then re-reads the board so it never shows something
    /// the engine doesn't have.
    private func commit(_ failure: String, _ work: () async throws -> Void) async {
        do { try await work(); error = nil } catch { self.error = ErrorWords.message(failure, error) }
        await load()
    }

    /// Several changes in one request. Selection clears once they've gone through.
    private func bulk(_ ops: [BoardOp], _ failure: String) async {
        guard !ops.isEmpty else { return }
        await commit(failure) {
            let r: BoardBulkResult = try await model.api.send("board/bulk", method: "POST", body: BoardBulkBody(ops: ops))
            if let bad = r.results.first(where: { !$0.ok }) {
                throw APIClient.APIError(status: 400, message: bad.error ?? "Part of that didn't work.")
            }
        }
        selection = []
    }

    /// One card per line, so pasting a list adds them all.
    private func addCards(_ text: String, to list: BoardList) async {
        let titles = text.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "-•*")).trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        guard !titles.isEmpty, let li = board?.lists.firstIndex(where: { $0.id == list.id }) else { return }
        withAnimation(.smooth) {
            for (i, t) in titles.enumerated() {
                board?.lists[li].cards.append(BoardCard(id: -Int.random(in: 1...Int(Int32.max)), listId: list.id, title: t,
                                                        body: "", tags: [], position: (list.cards.last?.position ?? -1) + 1 + i))
            }
        }
        await bulk(titles.map { BoardOp(op: "add", list: list.name, title: $0) }, "Couldn't add that card.")
    }

    private func save(_ card: BoardCard, _ d: CardDraft) async {
        if let (li, ci) = locate(card.id) {
            board?.lists[li].cards[ci].title = d.title
            board?.lists[li].cards[ci].body = d.body
            board?.lists[li].cards[ci].tags = d.tagList
            board?.lists[li].cards[ci].due = d.dueString
            board?.lists[li].cards[ci].checklist = d.checklist
        }
        await commit("Couldn't save that card.") {
            let _: BoardCard = try await model.api.send("board/cards/\(card.id)", method: "PATCH",
                body: CardPatchBody(title: d.title, body: d.body, tags: d.tagList.joined(separator: ", "),
                                    due: d.dueString ?? "", checklist: d.checklist))
        }
    }

    private func addList(_ name: String) async {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        await commit("Couldn't add that list.") { try await model.api.post("board/lists", ["name": .string(n)]) }
    }

    /// Moves a card into `listId`, before the card `before` (or to the end). The engine stores a raw
    /// position per card, so every card in the target list whose index changed is renumbered.
    private func move(_ id: Int, to listId: Int, before: Int?) async {
        guard id != before, var b = board, let (li, ci) = locate(id),
              let ti = b.lists.firstIndex(where: { $0.id == listId }) else { return }
        var card = b.lists[li].cards.remove(at: ci)
        card.listId = listId
        let at = before.flatMap { bid in b.lists[ti].cards.firstIndex { $0.id == bid } } ?? b.lists[ti].cards.count
        b.lists[ti].cards.insert(card, at: at)
        let changed = b.lists[ti].cards.enumerated().filter { $0.element.position != $0.offset || $0.element.id == id }
        for i in b.lists[ti].cards.indices { b.lists[ti].cards[i].position = i }
        withAnimation(.smooth) { board = b }
        await commit("Couldn't move that card.") {
            // The dragged card first, so a failure part-way leaves it where the user put it.
            for (i, c) in changed.filter({ $0.element.id == id }) + changed.filter({ $0.element.id != id }) {
                try await model.api.send("board/cards/\(c.id)/move", BoardMoveBody(toList: listId, position: i))
            }
        }
    }

    private func locate(_ id: Int) -> (Int, Int)? {
        guard let lists = board?.lists else { return nil }
        for (li, l) in lists.enumerated() {
            if let ci = l.cards.firstIndex(where: { $0.id == id }) { return (li, ci) }
        }
        return nil
    }
}

// MARK: Deadlines

/// Reads and writes the engine's deadline strings ("2026-11-13" or "2026-11-13T15:30", local time).
enum DueDate {
    enum Urgency { case overdue, soon, later }

    private static func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = format
        return f
    }
    private static let day = formatter("yyyy-MM-dd")
    private static let dayTime = formatter("yyyy-MM-dd'T'HH:mm")

    static func parse(_ s: String?) -> (date: Date, hasTime: Bool)? {
        guard let s, !s.isEmpty else { return nil }
        if let d = dayTime.date(from: s) { return (d, true) }
        if let d = day.date(from: s) { return (d, false) }
        return nil
    }

    static func string(_ date: Date, time: Bool) -> String { (time ? dayTime : day).string(from: date) }

    /// "Today", "Tomorrow 15:30", "Fri 13 Nov".
    static func label(_ s: String?) -> String? {
        guard let (d, hasTime) = parse(s) else { return nil }
        let cal = Calendar.current
        let dayText = cal.isDateInToday(d) ? "Today" : cal.isDateInTomorrow(d) ? "Tomorrow"
            : cal.isDateInYesterday(d) ? "Yesterday" : d.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
        return hasTime ? "\(dayText) \(d.formatted(date: .omitted, time: .shortened))" : dayText
    }

    static func urgency(_ s: String?, now: Date = .now) -> Urgency? {
        guard let (d, hasTime) = parse(s) else { return nil }
        let cal = Calendar.current
        let end = hasTime ? d : cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: d))!
        if end <= now { return .overdue }
        return end.timeIntervalSince(now) < 2 * 86_400 ? .soon : .later
    }
}

/// "1 overdue · 3 due this week", above the lists, when anything's due.
private struct DueSummary: View {
    var cards: [BoardCard]

    var body: some View {
        let overdue = cards.filter { DueDate.urgency($0.due) == .overdue }.count
        let week = cards.filter {
            guard let (d, _) = DueDate.parse($0.due) else { return false }
            return DueDate.urgency($0.due) != .overdue && d.timeIntervalSinceNow < 7 * 86_400
        }.count
        if overdue + week > 0 {
            HStack(spacing: 14) {
                if overdue > 0 { Label("\(overdue) overdue", systemImage: "exclamationmark.circle.fill").foregroundStyle(.red) }
                if week > 0 { Label("\(week) due this week", systemImage: "calendar").foregroundStyle(.secondary) }
            }
            .font(.callout.weight(.medium))
        }
    }
}

// MARK: Column

private struct ListColumn: View {
    var list: BoardList
    var cards: [BoardCard]
    var others: [BoardList]
    var archived: Bool
    var selection: Set<Int>
    var onTap: (BoardCard) -> Void
    var onSelect: (BoardCard) -> Void
    var onArchive: (BoardCard) -> Void
    var onDelete: (BoardCard) -> Void
    var onAdd: (String) -> Void
    var onMove: (_ card: Int, _ list: Int, _ before: Int?) -> Void

    @State private var targeted = false
    static let width: CGFloat = 248
    /// Text inset inside a card tile; the header and "Add Card" share it so everything lines up.
    static let inset: CGFloat = 12

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text(list.name).font(.headline)
                Text("\(cards.count)").font(.callout.monospacedDigit()).foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, Metrics.tight + Self.inset).padding(.top, 12).padding(.bottom, Metrics.tight)

            ScrollView(.vertical) {
                VStack(spacing: Metrics.tight) {
                    ForEach(cards) { card in
                        CardTile(card: card, others: others, selected: selection.contains(card.id),
                                 onTap: onTap, onSelect: onSelect, onArchive: onArchive, onDelete: onDelete,
                                 onMove: { listId in onMove(card.id, listId, nil) },
                                 onDrop: { dragged in onMove(dragged, list.id, card.id) })
                    }
                    if !archived { AddCardRow(listName: list.name, onAdd: onAdd) }
                }
                .padding(.horizontal, Metrics.tight).padding(.bottom, Metrics.tight)
            }
            .scrollIndicators(.never)
        }
        .frame(width: Self.width)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous)
                .strokeBorder(Color.accentColor.opacity(targeted ? 0.7 : 0), lineWidth: 2)
        }
        .dropDestination(for: String.self) { items, _ in
            guard !archived, let id = items.first.flatMap(Int.init) else { return false }
            onMove(id, list.id, nil)
            return true
        } isTargeted: { targeted = $0 && !archived }
        .animation(.easeOut(duration: 0.15), value: targeted)
    }
}

// MARK: Card

/// Tag colours stay the same for the same word, across launches.
enum TagColor {
    private static let palette: [Color] = [.blue, .purple, .pink, .orange, .teal, .green, .indigo, .brown, .mint, .red]
    static func of(_ tag: String) -> Color {
        palette[tag.lowercased().unicodeScalars.reduce(0) { ($0 &* 31 &+ Int($1.value)) & 0xFFFF } % palette.count]
    }
}

struct TagChip: View {
    var tag: String
    var body: some View {
        let c = TagColor.of(tag)
        Text(tag).font(.caption.weight(.medium)).foregroundStyle(c)
            .padding(.horizontal, 6).padding(.vertical, 1.5)
            .background(c.opacity(0.14), in: Capsule())
    }
}

private struct CardTile: View {
    var card: BoardCard
    var others: [BoardList]
    var selected: Bool
    var onTap: (BoardCard) -> Void
    var onSelect: (BoardCard) -> Void
    var onArchive: (BoardCard) -> Void
    var onDelete: (BoardCard) -> Void
    var onMove: (Int) -> Void
    var onDrop: (Int) -> Void

    @State private var dropAbove = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button { onTap(card) } label: {
            VStack(alignment: .leading, spacing: 6) {
                if !card.tags.isEmpty {
                    FlowTags(tags: card.tags)
                }
                Text(card.title).font(.body).multilineTextAlignment(.leading).lineLimit(4)
                if !card.body.isEmpty {
                    Text(card.body).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                if card.due != nil || !card.items.isEmpty {
                    HStack(spacing: 10) {
                        if let label = DueDate.label(card.due) { DueChip(label: label, urgency: DueDate.urgency(card.due)) }
                        if !card.items.isEmpty {
                            let done = card.items.filter(\.done).count
                            Label("\(done)/\(card.items.count)", systemImage: done == card.items.count ? "checkmark.square.fill" : "checkmark.square")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(done == card.items.count ? Color.green : Color.secondary)
                        }
                    }
                }
            }
            .padding(.horizontal, ListColumn.inset).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(scheme == .dark ? AnyShapeStyle(.quaternary) : AnyShapeStyle(.background),
                        in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(selected ? AnyShapeStyle(Color.accentColor) : AnyShapeStyle(.separator.opacity(0.6)), lineWidth: selected ? 2 : 1))
            .overlay(alignment: .topTrailing) {
                if selected {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.white, Color.accentColor)
                        .font(.body).padding(6)
                }
            }
            .shadow(color: .black.opacity(scheme == .dark ? 0 : 0.05), radius: 1, y: 1)
            .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
        .opacity(card.id < 0 ? 0.6 : 1)
        .disabled(card.id < 0)
        .overlay(alignment: .top) {
            Capsule().fill(Color.accentColor).frame(height: 3)
                .offset(y: -Metrics.tight / 2 - 1.5)
                .opacity(dropAbove ? 1 : 0)
        }
        .draggable(String(card.id)) {
            Text(card.title).padding(.horizontal, 12).padding(.vertical, 8)
                .frame(width: ListColumn.width - 2 * Metrics.tight, alignment: .leading)
                .background(.background, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .dropDestination(for: String.self) { items, _ in
            guard let id = items.first.flatMap(Int.init) else { return false }
            onDrop(id)
            return true
        } isTargeted: { dropAbove = $0 }
        .contextMenu {
            Button("Edit…") { onTap(card) }
            Button(selected ? "Deselect" : "Select") { onSelect(card) }
            Menu("Move To") {
                ForEach(others) { l in Button(l.name) { onMove(l.id) } }
            }
            .disabled(others.isEmpty)
            Divider()
            Button(card.isArchived ? "Restore" : "Archive") { onArchive(card) }
            Button("Delete…", role: .destructive) { onDelete(card) }
        }
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityHint("Opens the card. Command-click to select several. Drag to another list to move it.")
    }
}

private struct FlowTags: View {
    var tags: [String]
    var body: some View {
        // Up to three, then "+2": a card is a summary; the editor shows them all.
        HStack(spacing: 4) {
            ForEach(tags.prefix(3), id: \.self) { TagChip(tag: $0) }
            if tags.count > 3 { Text("+\(tags.count - 3)").font(.caption).foregroundStyle(.secondary) }
        }
        .lineLimit(1)
    }
}

private struct DueChip: View {
    var label: String
    var urgency: DueDate.Urgency?

    var body: some View {
        let color: Color = urgency == .overdue ? .red : urgency == .soon ? .orange : .secondary
        Label(label, systemImage: urgency == .overdue ? "exclamationmark.circle" : "calendar")
            .font(.caption.weight(urgency == .later ? .regular : .semibold))
            .foregroundStyle(color)
    }
}

// MARK: Selection

private struct SelectionBar: View {
    var count: Int
    var lists: [BoardList]
    var archived: Bool
    var onMove: (BoardList) -> Void
    var onArchive: () -> Void
    var onDelete: () -> Void
    var onDone: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text(count == 1 ? "1 card selected" : "\(count) cards selected").font(.callout.weight(.medium))
            Spacer(minLength: 12)
            if !archived {
                Menu("Move To") { ForEach(lists) { l in Button(l.name) { onMove(l) } } }
                    .fixedSize()
            }
            Button(archived ? "Restore" : "Archive", action: onArchive)
            Button("Delete…", role: .destructive, action: onDelete)
            Button("Done", action: onDone)
                .keyboardShortcut(.cancelAction)
                .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(.separator.opacity(0.5)))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        .frame(maxWidth: 620)
        .padding(.bottom, Metrics.gap)
        .padding(.horizontal, Metrics.page)
    }
}

// MARK: Add card

private struct AddCardRow: View {
    var listName: String
    var onAdd: (String) -> Void
    @State private var adding = false
    @State private var title = ""
    @FocusState private var focused: Bool

    var body: some View {
        if adding {
            VStack(alignment: .leading, spacing: 4) {
                TextField("Card title", text: $title, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...8)
                    .focused($focused)
                    .padding(.horizontal, ListColumn.inset).padding(.vertical, 10)
                    .background(.background, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.accentColor.opacity(0.6)))
                    .onSubmit {
                        onAdd(title)
                        title = ""
                        focused = true
                    }
                    .onExitCommand { cancel() }
                    .onChange(of: focused) { _, f in if !f { finish() } }
                    .onAppear { focused = true }
                Text("Paste a list to add one card per line.")
                    .font(.caption).foregroundStyle(.tertiary).padding(.horizontal, ListColumn.inset)
            }
        } else {
            Button { adding = true } label: {
                HStack(spacing: 6) {
                    Image(systemName: "plus")
                    Text("Add Card")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, ListColumn.inset).padding(.vertical, 7)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .accessibilityLabel("Add a card to \(listName)")
        }
    }

    /// Clicking away keeps what was typed, like Return.
    private func finish() {
        if !title.trimmingCharacters(in: .whitespaces).isEmpty { onAdd(title) }
        title = ""
        adding = false
    }

    /// Escape throws the draft away.
    private func cancel() {
        title = ""
        adding = false
    }
}

// MARK: Editor

struct CardDraft {
    var title: String
    var body: String
    var tags: String
    var hasDue: Bool
    var dueDate: Date
    var dueHasTime: Bool
    var checklist: [ChecklistItem]

    var tagList: [String] { tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }
    var dueString: String? { hasDue ? DueDate.string(dueDate, time: dueHasTime) : nil }
}

struct CardEditor: View {
    var card: BoardCard
    var onSave: (CardDraft) -> Void
    var onArchive: () -> Void
    var onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var draft: CardDraft
    @State private var newItem = ""

    init(card: BoardCard, onSave: @escaping (CardDraft) -> Void, onArchive: @escaping () -> Void, onDelete: @escaping () -> Void) {
        self.card = card
        self.onSave = onSave
        self.onArchive = onArchive
        self.onDelete = onDelete
        let due = DueDate.parse(card.due)
        let tomorrow9 = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0,
                                              of: Calendar.current.date(byAdding: .day, value: 1, to: .now)!)!
        _draft = State(initialValue: CardDraft(title: card.title, body: card.body, tags: card.tags.joined(separator: ", "),
                                               hasDue: due != nil, dueDate: due?.date ?? tomorrow9,
                                               dueHasTime: due?.hasTime ?? false, checklist: card.items))
    }

    private var trimmed: String { draft.title.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Form {
            Section {
                TextField("Title", text: $draft.title)
                TextField("Notes", text: $draft.body, prompt: Text("Add more detail"), axis: .vertical)
                    .lineLimit(3...10)
                TextField("Tags", text: $draft.tags, prompt: Text("Separate with commas"))
                if !draft.tagList.isEmpty {
                    HStack(spacing: 4) { ForEach(draft.tagList, id: \.self) { TagChip(tag: $0) } }
                }
            }

            Section {
                Toggle("Due date", isOn: $draft.hasDue.animation(.smooth(duration: 0.2))).toggleStyle(.vox)
                if draft.hasDue {
                    DatePicker("Day", selection: $draft.dueDate, displayedComponents: .date)
                    Toggle("At a set time", isOn: $draft.dueHasTime).toggleStyle(.vox)
                    if draft.dueHasTime {
                        DatePicker("Time", selection: $draft.dueDate, displayedComponents: .hourAndMinute)
                    }
                }
            } footer: {
                if draft.hasDue {
                    Text(draft.dueHasTime ? "Vox reminds you at that time." : "Vox reminds you at 9:00 that morning.")
                        .foregroundStyle(.secondary)
                }
            }

            Section("Checklist") {
                ForEach($draft.checklist, id: \.self) { $item in
                    HStack {
                        Toggle(item.text, isOn: $item.done).toggleStyle(.checkbox)
                        Spacer()
                        Button("Remove", systemImage: "minus.circle.fill") { draft.checklist.removeAll { $0 == item } }
                            .labelStyle(.iconOnly).buttonStyle(.borderless).foregroundStyle(.secondary)
                    }
                }
                TextField("Add an item", text: $newItem, prompt: Text("Add an item"))
                    .labelsHidden()
                    .onSubmit {
                        let t = newItem.trimmingCharacters(in: .whitespaces)
                        if !t.isEmpty { draft.checklist.append(ChecklistItem(text: t, done: false)) }
                        newItem = ""
                    }
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .frame(minHeight: 420, maxHeight: 640)
        .toolbar {
            ToolbarItemGroup(placement: .destructiveAction) {
                Button("Delete…", role: .destructive) { dismiss(); onDelete() }
                Button(card.isArchived ? "Restore" : "Archive") { onArchive(); dismiss() }
            }
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") {
                    var d = draft
                    d.title = trimmed
                    d.body = d.body.trimmingCharacters(in: .whitespacesAndNewlines)
                    let pending = newItem.trimmingCharacters(in: .whitespaces)
                    if !pending.isEmpty { d.checklist.append(ChecklistItem(text: pending, done: false)) }
                    onSave(d)
                    dismiss()
                }
                .disabled(trimmed.isEmpty)
            }
        }
    }
}
