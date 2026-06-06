"""Image info / EXIF dialog — a non-modal Toplevel that follows navigation.

AIDEV-NOTE: All decode/sanitize/redact logic lives in metadata.py (pure, tested).
This widget only renders sections, hosts the curated edit fields, and exposes the
keep/strip and GPS-redaction actions. Edits/wipes are written on Save As only.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

from pxv import metadata

if TYPE_CHECKING:
    from pxv.app import PxvApp


class InfoDialog(tk.Toplevel):
    """Non-modal info panel showing file facts, EXIF, edit fields, and wipe actions."""

    def __init__(self, app: PxvApp) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("pxv: Image Info")
        self.resizable(False, False)
        self.transient(app.root)

        self._keep_var = tk.BooleanVar(value=app.image_model.keep_metadata)
        self._edit_vars: dict[str, tk.StringVar] = {}
        self._tags_shown = False

        self._body = ttk.Frame(self, padding=10)
        self._body.pack(fill=tk.BOTH, expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _: self._on_close())

        self.refresh()

        # Position beside the parent window (matches EnhancementDialog).
        self.update_idletasks()
        px = app.root.winfo_x() + app.root.winfo_width() + 10
        py = app.root.winfo_y()
        self.geometry(f"+{px}+{py}")

    # --- rendering -------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the panel from the currently-loaded image's metadata."""
        for child in self._body.winfo_children():
            child.destroy()
        self._edit_vars.clear()
        self._tags_shown = False

        meta = self.app.image_model.metadata
        if meta is None:
            ttk.Label(self._body, text="No image loaded.").pack(anchor=tk.W)
            return

        self._keep_var.set(self.app.image_model.keep_metadata)
        self._build_sections(meta)
        self._build_editor(meta)
        self._build_alltags(meta)
        self._build_footer(meta)

    def _build_sections(self, meta: metadata.ImageMetadata) -> None:
        for section in metadata.build_sections(meta):
            frame = ttk.LabelFrame(self._body, text=section.title, padding=6)
            frame.pack(fill=tk.X, pady=(0, 6))
            for row, (label, value) in enumerate(section.rows):
                ttk.Label(frame, text=label, anchor=tk.E, width=12).grid(
                    row=row, column=0, sticky=tk.E, padx=(0, 6), pady=1
                )
                ttk.Label(frame, text=value).grid(row=row, column=1, sticky=tk.W, pady=1)
            if section.title == "Location":
                ttk.Button(frame, text="Remove GPS", command=self._on_remove_gps).grid(
                    row=0, column=2, padx=(8, 0)
                )

    def _build_editor(self, meta: metadata.ImageMetadata) -> None:
        frame = ttk.LabelFrame(
            self._body, text='Edit (written only if "keep" is checked)', padding=6
        )
        frame.pack(fill=tk.X, pady=(0, 6))
        for row, (key, label, _ifd, _tag) in enumerate(metadata.EDITABLE_FIELDS):
            var = tk.StringVar(value=metadata.get_editable(meta, key))
            var.trace_add("write", self._make_edit_callback(key, var))
            self._edit_vars[key] = var
            ttk.Label(frame, text=label, anchor=tk.E, width=12).grid(
                row=row, column=0, sticky=tk.E, padx=(0, 6), pady=1
            )
            ttk.Entry(frame, textvariable=var, width=32).grid(
                row=row, column=1, sticky=tk.W, pady=1
            )

    def _build_alltags(self, meta: metadata.ImageMetadata) -> None:
        rows = metadata.all_tags(meta)
        frame = ttk.Frame(self._body)
        frame.pack(fill=tk.X, pady=(0, 6))
        toggle = ttk.Button(frame, text=f"Show all tags ({len(rows)})")
        toggle.pack(anchor=tk.W)
        # AIDEV-NOTE: the tags list is parented to this section frame (not _body) so
        # the expansion appears in place, above the footer, instead of below it.
        self._tags_frame = ttk.Frame(frame)
        toggle.configure(command=lambda: self._toggle_tags(toggle, rows))

    def _toggle_tags(self, toggle: ttk.Button, rows: list[tuple[int, str, str]]) -> None:
        if self._tags_shown:
            self._tags_frame.pack_forget()
            for child in self._tags_frame.winfo_children():
                child.destroy()
            toggle.configure(text=f"Show all tags ({len(rows)})")
            self._tags_shown = False
            return
        tree = ttk.Treeview(self._tags_frame, columns=("name", "value"), show="headings", height=8)
        tree.heading("name", text="Tag")
        tree.heading("value", text="Value")
        tree.column("name", width=160, anchor=tk.W)
        tree.column("value", width=260, anchor=tk.W)
        for _tag_id, name, value in rows:
            tree.insert("", tk.END, values=(name, value))
        scroll = ttk.Scrollbar(self._tags_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tags_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        toggle.configure(text="Hide all tags")
        self._tags_shown = True

    def _build_footer(self, meta: metadata.ImageMetadata) -> None:
        frame = ttk.Frame(self._body)
        frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Checkbutton(
            frame,
            text="Keep metadata on save",
            variable=self._keep_var,
            command=self._on_keep_toggle,
        ).pack(side=tk.LEFT)
        ttk.Button(frame, text="Strip all", command=self._on_strip_all, width=10).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(frame, text="Close", command=self._on_close, width=8).pack(
            side=tk.RIGHT, padx=4
        )

    # --- actions ---------------------------------------------------------

    def _make_edit_callback(self, key: str, var: tk.StringVar) -> Callable[..., None]:
        def _callback(*_args: object) -> None:
            meta = self.app.image_model.metadata
            if meta is not None:
                metadata.set_editable(meta, key, var.get())

        return _callback

    def _on_keep_toggle(self) -> None:
        self.app.image_model.keep_metadata = self._keep_var.get()

    def _on_strip_all(self) -> None:
        self._keep_var.set(False)
        self.app.image_model.keep_metadata = False

    def _on_remove_gps(self) -> None:
        meta = self.app.image_model.metadata
        if meta is not None:
            metadata.redact_gps(meta.exif)
            self.refresh()

    def _on_close(self) -> None:
        # AIDEV-NOTE: Closing via the "Close" button (a pointer action) otherwise
        # leaves the app keyboard-dead — every root-bound shortcut stops firing
        # while mouse/rubber-band events keep working. destroy() clears the input
        # focus this dialog held, so the focus reclaim MUST come AFTER destroy().
        # See PxvApp.restore_main_focus.
        self.app.info_dialog = None
        self.destroy()
        self.app.restore_main_focus()
