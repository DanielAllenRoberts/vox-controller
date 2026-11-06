import SwiftUI

/// A kanban board: lists side by side, cards you can add, edit, drag between lists, and delete.
/// Vox's agents read and write the same board, so it doubles as a shared to-do list.
struct BoardView: View {
    @Environment(AppModel.self) private var model
    @State private var board: Board?
    @State private var error: String?
    @State private var editing: BoardCard?
    @State private var deleting: BoardCard?
    @State private var addingList = false
    @State private var newListName = ""

    var body: some View {
        RequiresEngine {
            content
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Add List", systemImage: "plus") { newListName = ""; addingList = true }
                            .help("Add a list")
                    }
                }
                .task { await load() }
                .sheet(item: $editing) { card in
                    CardEditor(card: card) { title, body, tags in
                        Task { await save(card, title: title, body: body, tags: tags) }
                    } onDelete: {
                        Task { await delete(card) }
                    }
                }
                .confirmationDialog("Delete \u{201C}\(deleting?.title ?? "")\u{201D}?", isPresented: .init(
                    get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
                    Button("Delete Card", role: .destructive) { if let c = deleting { Task { await delete(c) } } }
                } message: {
                    Text("This can't be undone.")
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

    @ViewBuilder
    private var content: some View {
        if let board {
            if board.lists.isEmpty {
                ContentUnavailableView {
                    Label("No lists yet", systemImage: "rectangle.split.3x1")
                } description: {
                    Text("Add a list, then add cards to it. Vox can read and update this board too.")
                } actions: {
                    Button("Add List") { newListName = ""; addingList = true }
                }
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    if let error { ErrorLine(text: error).padding(.horizontal, Metrics.page).padding(.top, 12) }
                    ScrollView(.horizontal) {
                        HStack(alignment: .top, spacing: Metrics.gap) {
                            ForEach(board.lists) { list in
                                ListColumn(list: list, others: board.lists.filter { $0.id != list.id },
                                           onOpen: { editing = $0 },
                                           onDelete: { deleting = $0 },
                                           onAdd: { title in Task { await addCard(title, to: list) } },
                                           onMove: { id, listId, before in Task { await move(id, to: listId, before: before) } })
                            }
                        }
                        .padding(Metrics.page)
                        .frame(maxHeight: .infinity, alignment: .top)
                    }
                }
            }
        } else if let error {
            ContentUnavailableView {
                Label("Couldn't load the board", systemImage: "exclamationmark.triangle")
            } description: { Text(error) } actions: { Button("Try Again") { Task { await load() } } }
        } else {
            ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    // MARK: Data

    private func load() async {
        do { board = try await model.api.get("board"); error = nil }
        catch { self.error = error.localizedDescription }
    }

    /// Runs a change against the engine, then re-reads the board so it never shows something
    /// the engine doesn't have.
    private func commit(_ work: () async throws -> Void) async {
        do { try await work(); error = nil } catch { self.error = error.localizedDescription }
        await load()
    }

    private func addCard(_ title: String, to list: BoardList) async {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, let li = board?.lists.firstIndex(where: { $0.id == list.id }) else { return }
        let temp = BoardCard(id: -Int.random(in: 1...Int(Int32.max)), listId: list.id, title: t, body: "", tags: [],
                             position: (list.cards.last?.position ?? -1) + 1)
        withAnimation(.smooth) { board?.lists[li].cards.append(temp) }
        await commit { try await model.api.post("board/cards", ["list": .string(list.name), "title": .string(t)]) }
    }

    private func save(_ card: BoardCard, title: String, body: String, tags: String) async {
        if let (li, ci) = locate(card.id) {
            board?.lists[li].cards[ci].title = title
            board?.lists[li].cards[ci].body = body
            board?.lists[li].cards[ci].tags = tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        }
        await commit {
            try await model.api.patch("board/cards/\(card.id)", ["title": .string(title), "body": .string(body), "tags": .string(tags)])
        }
    }

    private func delete(_ card: BoardCard) async {
        if let (li, ci) = locate(card.id) { _ = withAnimation(.smooth) { board?.lists[li].cards.remove(at: ci) } }
        await commit { try await model.api.delete("board/cards/\(card.id)") }
    }

    private func addList(_ name: String) async {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        await commit { try await model.api.post("board/lists", ["name": .string(n)]) }
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
        await commit {
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

// MARK: Column

private struct ListColumn: View {
    var list: BoardList
    var others: [BoardList]
    var onOpen: (BoardCard) -> Void
    var onDelete: (BoardCard) -> Void
    var onAdd: (String) -> Void
    var onMove: (_ card: Int, _ list: Int, _ before: Int?) -> Void

    @State private var targeted = false
    static let width: CGFloat = 232
    /// Text inset inside a card tile; the header and "Add Card" share it so everything lines up.
    static let inset: CGFloat = 12

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text(list.name).font(.headline)
                Text("\(list.cards.count)").font(.callout.monospacedDigit()).foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, Metrics.tight + Self.inset).padding(.top, 12).padding(.bottom, Metrics.tight)

            ScrollView(.vertical) {
                VStack(spacing: Metrics.tight) {
                    ForEach(list.cards) { card in
                        CardTile(card: card, others: others, onOpen: onOpen, onDelete: onDelete,
                                 onMove: { listId in onMove(card.id, listId, nil) },
                                 onDrop: { dragged in onMove(dragged, list.id, card.id) })
                    }
                    AddCardRow(listName: list.name, onAdd: onAdd)
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
            guard let id = items.first.flatMap(Int.init) else { return false }
            onMove(id, list.id, nil)
            return true
        } isTargeted: { targeted = $0 }
        .animation(.easeOut(duration: 0.15), value: targeted)
    }
}

// MARK: Card

private struct CardTile: View {
    var card: BoardCard
    var others: [BoardList]
    var onOpen: (BoardCard) -> Void
    var onDelete: (BoardCard) -> Void
    var onMove: (Int) -> Void
    var onDrop: (Int) -> Void

    @State private var dropAbove = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button { onOpen(card) } label: {
            VStack(alignment: .leading, spacing: 6) {
                Text(card.title).font(.body).multilineTextAlignment(.leading).lineLimit(4)
                if !card.body.isEmpty {
                    Text(card.body).font(.callout).foregroundStyle(.secondary).lineLimit(3)
                        .multilineTextAlignment(.leading)
                }
                if !card.tags.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(card.tags, id: \.self) { tag in
                            Text(tag).font(.caption).foregroundStyle(.secondary)
                                .padding(.horizontal, 6).padding(.vertical, 1)
                                .background(.quaternary, in: Capsule())
                        }
                    }
                }
            }
            .padding(.horizontal, ListColumn.inset).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(scheme == .dark ? AnyShapeStyle(.quaternary) : AnyShapeStyle(.background),
                        in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(.separator.opacity(0.6)))
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
            Button("Edit…") { onOpen(card) }
            Menu("Move To") {
                ForEach(others) { l in Button(l.name) { onMove(l.id) } }
            }
            .disabled(others.isEmpty)
            Divider()
            Button("Delete…", role: .destructive) { onDelete(card) }
        }
        .accessibilityHint("Opens the card. Drag to another list to move it.")
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
            TextField("Card title", text: $title, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .focused($focused)
                .padding(.horizontal, ListColumn.inset).padding(.vertical, 10)
                .background(.background, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.accentColor.opacity(0.6)))
                .onSubmit {
                    onAdd(title)
                    title = ""
                    focused = true
                }
                .onExitCommand { finish() }
                .onChange(of: focused) { _, f in if !f { finish() } }
                .onAppear { focused = true }
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

    private func finish() {
        if !title.trimmingCharacters(in: .whitespaces).isEmpty { onAdd(title) }
        title = ""
        adding = false
    }
}

// MARK: Editor

private struct CardEditor: View {
    var card: BoardCard
    var onSave: (_ title: String, _ body: String, _ tags: String) -> Void
    var onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var title: String
    @State private var text: String
    @State private var tags: String
    @State private var confirmDelete = false

    init(card: BoardCard, onSave: @escaping (String, String, String) -> Void, onDelete: @escaping () -> Void) {
        self.card = card
        self.onSave = onSave
        self.onDelete = onDelete
        _title = State(initialValue: card.title)
        _text = State(initialValue: card.body)
        _tags = State(initialValue: card.tags.joined(separator: ", "))
    }

    private var trimmed: String { title.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Form {
            Section {
                TextField("Title", text: $title)
                TextField("Notes", text: $text, prompt: Text("Add more detail"), axis: .vertical)
                    .lineLimit(5...12)
                TextField("Tags", text: $tags, prompt: Text("Separate with commas"))
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .toolbar {
            ToolbarItem(placement: .destructiveAction) {
                Button("Delete…", role: .destructive) { confirmDelete = true }
            }
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") {
                    onSave(trimmed, text.trimmingCharacters(in: .whitespacesAndNewlines), tags)
                    dismiss()
                }
                .disabled(trimmed.isEmpty)
            }
        }
        .confirmationDialog("Delete \u{201C}\(card.title)\u{201D}?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete Card", role: .destructive) { onDelete(); dismiss() }
        } message: {
            Text("This can't be undone.")
        }
    }
}

private struct ErrorLine: View {
    var text: String
    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(.red)
    }
}
