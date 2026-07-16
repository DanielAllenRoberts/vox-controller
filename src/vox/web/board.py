"""Workspace-board bridge for the dashboard — read + edits over the SQLite board store.

Backs the dashboard's **Board** page and the agent's knowledge-base tools (idea #51,
``vox.board_store``). Self-contained + guarded like the other bridge modules
(``commands``/``rules``): a missing/empty DB degrades to an empty board, never a 500. All shapes
are camelCase, already produced by ``board_store`` (``board_snapshot``/``_card_dict``), so this
module is a thin, validated pass-through. ``_conn`` uses ``board_store.build`` so the default board
("Workspace" → To Do/Doing/Done) always exists on first read.
"""

from __future__ import annotations

from vox import board_store


def _conn():
    # build() = connect + schema + idempotent seed → the default board always exists.
    return board_store.build()


# --- read ----------------------------------------------------------------------------------------

def snapshot(board=None) -> dict:
    """The whole board as nested lists→cards (camelCase) for the dashboard + agent read."""
    conn = _conn()
    try:
        return board_store.board_snapshot(conn, board)
    finally:
        conn.close()


def search(query: str, limit: int = 50) -> list:
    """Substring search across card title/body/tags — the agent's knowledge lookup."""
    conn = _conn()
    try:
        return board_store.search(conn, query, limit)
    finally:
        conn.close()


# --- edits (used by dashboard drag/edit AND the agent's board tools) ------------------------------

def create_card(list_name: str, title: str, body: str = "", tags="", board=None) -> dict:
    """Add a card to a column (resolved by name). Raises ValueError on blank title / unknown list."""
    conn = _conn()
    try:
        return board_store.add_card(conn, list_name, title, body, tags, board)
    finally:
        conn.close()


def update_card(card_id, *, title=None, body=None, tags=None) -> dict | None:
    conn = _conn()
    try:
        return board_store.update_card(conn, int(card_id), title=title, body=body, tags=tags)
    finally:
        conn.close()


def move_card(card_id, to_list, position=None, board=None) -> dict | None:
    conn = _conn()
    try:
        return board_store.move_card(conn, int(card_id), to_list, position, board)
    finally:
        conn.close()


def delete_card(card_id) -> bool:
    conn = _conn()
    try:
        return board_store.delete_card(conn, int(card_id))
    finally:
        conn.close()


def create_list(name: str, board=None) -> dict:
    """Add a column to a board. Raises ValueError on a blank/duplicate name."""
    conn = _conn()
    try:
        return board_store.add_list(conn, name, board)
    finally:
        conn.close()
