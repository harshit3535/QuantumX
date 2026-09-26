from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext

from core.models import ResponseSegment
from ui.theme import CODE_BG, DANGER, FONT, MATH_BG, MUTED, PANEL, SUCCESS, TEXT, WARN, MONO


class StatusBar(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=PANEL)
        self.label = tk.Label(self, text="Ready", bg=PANEL, fg=MUTED, font=FONT, anchor="w")
        self.label.pack(fill="x", padx=10, pady=7)

    def set(self, text: str):
        self.label.config(text=text)


class RichResponseView(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=PANEL)
        self.text = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=FONT,
            padx=12,
            pady=12,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("code", font=MONO, background=CODE_BG, foreground=TEXT, lmargin1=16, lmargin2=16, spacing1=2, spacing3=8)
        self.text.tag_configure("math", font=("Cambria Math", 11), background=MATH_BG, foreground=TEXT, lmargin1=16, lmargin2=16, spacing1=4, spacing3=8)
        self.text.tag_configure("warning", foreground=WARN)
        self.text.tag_configure("error", foreground=DANGER)
        self.text.tag_configure("meta", foreground=MUTED)
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.configure(state="disabled")

    def append(self, heading: str, segments: list[ResponseSegment]):
        self.text.configure(state="normal")
        self.text.insert(tk.END, f"\n{heading}\n", "meta")
        for seg in segments:
            tag = seg.type if seg.type in {"code", "math", "warning", "error"} else None
            content = seg.content
            if seg.type == "code" and seg.language:
                content = f"[{seg.language}]\n{content}\n"
            elif seg.type == "math":
                pretty = seg.metadata.get("pretty")
                if pretty:
                    content = f"{pretty}\n"
                else:
                    content = f"{content}\n"
            else:
                content = f"{content}\n"
            self.text.insert(tk.END, content, tag)
            self.text.insert(tk.END, "\n")
        self.text.see(tk.END)
        self.text.configure(state="disabled")
