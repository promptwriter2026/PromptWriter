import tkinter
import webbrowser

import customtkinter as ctk

from promptwriter import __version__


HELP_LINKS = (
    ("Google Gemini API (Google AI Studio)", "https://aistudio.google.com/"),
    ("Groq API", "https://console.groq.com/"),
    ("LM Studio", "https://lmstudio.ai/"),
)

KOFI_URL = "https://ko-fi.com/promptwriter"
HELP_GUIDE_TAB = "Guide / Usage"
HELP_LICENSE_TAB = "License & Disclaimer"

LINK_COLOR = "#4DA3FF"
KOFI_COLOR = "#ff5e5b"
KOFI_HOVER_COLOR = "#d94e4b"

MIT_LICENSE_TEXT = (
    "Copyright (c) 2026 The PWLP Authors\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a "
    "copy of this software and associated documentation files (the "
    "\"Software\"), to deal in the Software without restriction, including "
    "without limitation the rights to use, copy, modify, merge, publish, "
    "distribute, sublicense, and/or sell copies of the Software, and to "
    "permit persons to whom the Software is furnished to do so, subject to "
    "the following conditions:\n\n"
    "The above copyright notice and this permission notice shall be included "
    "in all copies or substantial portions of the Software.\n\n"
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, "
    "EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF "
    "MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. "
    "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY "
    "CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, "
    "TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE "
    "SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."
)

LICENSE_ENTRIES = (
    ("heading", "MIT License\n"),
    (
        "body",
        "PWLP is released under the MIT License, reproduced below. The same "
        "text is shipped in the LICENSE file in the project root; "
        "third-party licenses are listed in THIRD_PARTY_NOTICES.md. You may "
        "use, modify, and redistribute PWLP, provided the copyright and "
        "permission notice are kept.\n\n",
    ),
    ("body", MIT_LICENSE_TEXT + "\n\n"),
    ("heading", "No warranty\n"),
    (
        "body",
        "PWLP is completely free to use. It is distributed as-is, without any "
        "warranty of any kind, express or implied, including fitness for a "
        "particular purpose, accuracy, or non-infringement. No fee is charged "
        "for the app, and no support or update commitment is made.\n\n",
    ),
    (
        "body",
        "You are responsible for how you use PWLP and for everything it "
        "produces. Generated prompts and images may be inaccurate, biased, "
        "offensive, or unsuitable for your purpose, so review them before use. "
        "You are also responsible for complying with the terms of any model "
        "provider, service, or platform you use, and for anything you publish "
        "or generate with it.\n\n",
    ),
    (
        "body",
        "The author accepts no liability for outputs, for losses caused by "
        "third-party services (including LM Studio, Gemini, Groq, ComfyUI, or "
        "Forge Neo), for API costs or account issues, or for data loss. "
        "Deleting personal data, clearing history, or resetting the app is "
        "permanent; keep your own copies of anything important.\n\n",
    ),
    ("heading", "Third-party names\n"),
    (
        "body",
        "LM Studio, Gemini, and Groq are third-party names used only to "
        "describe compatibility and integration options. PWLP is not "
        "affiliated with, endorsed by, or sponsored by their owners, and those "
        "services are governed by their own terms and privacy policies.\n\n",
    ),
    ("heading", "Support PWLP\n"),
    (
        "body",
        "PWLP is free and has no paid tiers. If it is useful to you, you can "
        "support development at ",
    ),
    ("link", ("Ko-fi", KOFI_URL)),
    ("body", " (opens in your browser).\n\n"),
    ("muted", "Use PWLP at your own risk.\n"),
)


def open_external_url(url):
    try:
        webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        return False
    return True


class HelpTabMixin:
    def _build_help_tab(self):
        tab = self.help_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.help_tabview = ctk.CTkTabview(tab)
        self.help_tabview.grid(
            row=0, column=0, padx=8, pady=8, sticky="nsew"
        )
        guide = self.help_tabview.add(HELP_GUIDE_TAB)
        license_tab = self.help_tabview.add(HELP_LICENSE_TAB)
        guide.grid_columnconfigure(0, weight=1)
        guide.grid_rowconfigure(2, weight=1)
        license_tab.grid_columnconfigure(0, weight=1)
        license_tab.grid_rowconfigure(0, weight=1)

        textbox_options = {
            "wrap": "word",
            "font": ctk.CTkFont(family="Segoe UI", size=13),
        }

        self.help_intro_text = ctk.CTkTextbox(
            guide, height=200, **textbox_options
        )
        self.help_intro_text.grid(
            row=0, column=0, padx=8, pady=(8, 0), sticky="ew"
        )
        self._add_tooltip(
            self.help_intro_text,
            "Short introduction. Blue links open in your browser.",
        )
        self._insert_help_entries(
            self._help_intro_entries(), self.help_intro_text
        )
        self.help_intro_text.configure(state="disabled")
        self.help_intro_text.bind(
            "<Configure>", self._fit_help_intro_height, add="+"
        )

        self.kofi_button = ctk.CTkButton(
            guide,
            text="Support PWLP on Ko-fi",
            command=self._open_kofi,
            width=230,
            height=34,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=KOFI_COLOR,
            hover_color=KOFI_HOVER_COLOR,
        )
        self.kofi_button.grid(
            row=1, column=0, padx=12, pady=(2, 8), sticky="w"
        )
        self._add_tooltip(
            self.kofi_button,
            "Open the Ko-fi page in your default browser.",
        )

        self.help_text = ctk.CTkTextbox(
            guide, activate_scrollbars=True, **textbox_options
        )
        self.help_text.grid(
            row=2, column=0, padx=8, pady=(0, 8), sticky="nsew"
        )
        self._add_tooltip(
            self.help_text,
            "Plain-text reference. Blue links open in your browser; "
            "the panel scrolls with the mouse wheel.",
        )
        self._insert_help_entries(self._help_guide_entries(), self.help_text)
        self.help_text.configure(state="disabled")

        self.help_license_text = ctk.CTkTextbox(
            license_tab, activate_scrollbars=True, **textbox_options
        )
        self.help_license_text.grid(
            row=0, column=0, padx=8, pady=8, sticky="nsew"
        )
        self._add_tooltip(
            self.help_license_text,
            "License and disclaimer. The panel scrolls with the mouse wheel.",
        )
        self._insert_help_entries(LICENSE_ENTRIES, self.help_license_text)
        self.help_license_text.configure(state="disabled")

    def _help_intro_entries(self):
        gemini_name, gemini_url = next(
            link
            for link in HELP_LINKS
            if link[0] == "Google Gemini API (Google AI Studio)"
        )
        _, groq_url = next(link for link in HELP_LINKS if link[0] == "Groq API")
        _, lm_studio_url = next(
            link for link in HELP_LINKS if link[0] == "LM Studio"
        )
        return [
            ("title", "PWLP — Prompt Writer for Lazy People\n"),
            ("muted", f"Version {__version__}\n\n"),
            (
                "body",
                "PWLP turns a rough idea into a detailed English prompt using the "
                "engine and system prompt you select. Pick an engine, pick a "
                "system prompt, type the idea, then press Generate Prompt. The "
                "result can be copied and is saved to History.\n\n",
            ),
            ("body", "PWLP was tested with "),
            ("link", ("LM Studio", lm_studio_url)),
            (
                "body",
                " and works with Gemini or Groq for cloud generation. See the "
                "Guide below for every tab and control.\n\n",
            ),
            (
                "body",
                "The System prompt matters most: it decides the output format, "
                "the wording style, and how well the result fits a target "
                "model/architecture (SDXL, Flux, Pony, ...). Built-in prompts are "
                "starting points; edit or create your own under Settings > Text "
                "System Prompts (or Vision System Prompts) to change the actual "
                "output.\n\n",
            ),
            (
                "body",
                "No local GPU? Use a free cloud key instead. Create a key at ",
            ),
            ("link", (gemini_name, gemini_url)),
            ("body", " or "),
            ("link", ("Groq API", groq_url)),
            (
                "body",
                ", paste it into Settings > Gemini API key or Groq API key, click "
                "Save Settings, then choose Gemini or Groq as the LLM engine. "
                "Cloud engines need no LM Studio and can be used alongside local "
                "models.\n\n",
            ),
            (
                "body",
                "The header shows live GPU VRAM usage on NVIDIA GPUs only. On "
                "other GPUs, or when no NVIDIA driver is available, it shows "
                "\"VRAM: Not supported\" and the VRAM pre-flight is skipped. A "
                "Local generation may offer to unload ComfyUI / Forge Neo models "
                "first when VRAM is above 50% and no local model is loaded.\n\n",
            ),
        ]

    def _help_guide_entries(self):
        entries = [
            ("heading", "Generator tab\n"),
            (
                "body",
                "LLM engine — Gemini, Groq, or Local (LM Studio). Changing it "
                "switches the model list below it.\n",
            ),
            (
                "body",
                "Selected API model — model used for generation. Fetch reloads "
                "the provider's model list; the ⚙ button opens that model's "
                "sampling profile (temperature, Top-P, Presence Penalty on "
                "Groq/Local, Max Tokens, plus Local-only Min-P, Repeat Penalty, "
                "Context Length, Disable Thinking).\n",
            ),
            (
                "body",
                "Presence Penalty — Groq and Local only (hidden for Gemini); "
                "0.00 to 2.00, sent only when above 0.00, and shown in the "
                "compact profile summary only while active.\n",
            ),
            (
                "body",
                "System prompt — the instructions that shape the generated "
                "prompt; choices come from the system_prompts folder.\n",
            ),
            (
                "body",
                "Camera / lens — optionally adds photography keywords; entries are "
                "added in Settings.\n",
            ),
            (
                "body",
                "Character / LoRA — optionally applies a saved character profile "
                "and forces its trigger words at the start of the prompt.\n",
            ),
            (
                "body",
                "Temp slider — 0.00 to 1.00; higher values give more varied "
                "prompts. Saved values above 1.00 are capped to 1.00. The gray "
                "line shows the active model profile.\n",
            ),
            (
                "body",
                "Auto-Unload Model from VRAM — Local only; unloads the model after "
                "each successful generation.\n",
            ),
            (
                "body",
                "Unload Model — Local only; unloads it now. LM Studio Status shows "
                "which model is currently loaded.\n",
            ),
            ("body", "Rough idea — the text to expand; Clear empties it.\n"),
            (
                "body",
                "Generate Prompt — runs the selected engine and clears the "
                "previous output. Status, quota, and elapsed time appear above the "
                "result.\n",
            ),
            (
                "body",
                "Enforce Single-Line Prompts — joins multi-line output into "
                "single-line prompts; shared with the Image to Prompt tab.\n",
            ),
            (
                "body",
                "Generated prompt — the result; right-click for Cut, Copy, Paste, "
                "Select All, or use Copy to Clipboard.\n\n",
            ),
            ("heading", "Image to Prompt tab\n"),
            (
                "body",
                "LLM engine — same engines as Generator and set independently.\n",
            ),
            (
                "body",
                "Selected API model — model used to analyze the image; Fetch and "
                "⚙ work as on the Generator tab.\n",
            ),
            (
                "body",
                "System prompt — vision prompts from the system_prompts_vision "
                "folder.\n",
            ),
            (
                "body",
                "Character / LoRA — uses the saved character profile to replace "
                "the person's appearance while keeping pose, clothing, and scene.\n",
            ),
            (
                "body",
                "Auto-Unload / Unload Model / LM Studio Status — Local only; same "
                "behavior as on the Generator tab.\n",
            ),
            (
                "body",
                "Image preview — drop an image onto it or use Select Image. A "
                "preview of the loaded image is shown.\n",
            ),
            (
                "body",
                "Additional Context / Instructions — optional text to steer the "
                "analysis (pose changes, extra details, ...).\n",
            ),
            ("body", "Select Image — opens a file dialog to load a reference image.\n"),
            (
                "body",
                "Generate Prompt from Image — analyzes the image and writes the "
                "prompt; analysis runs in the background.\n",
            ),
            (
                "body",
                "Temp slider — 0.00 to 1.00 for the vision model; the gray line "
                "shows the active profile.\n",
            ),
            (
                "body",
                "Enforce Single-Line Prompts — same shared option as on the "
                "Generator tab.\n",
            ),
            (
                "body",
                "Output Prompt — the result; Copy to Clipboard copies it.\n\n",
            ),
            ("heading", "Settings tab\n"),
            (
                "body",
                "Gemini API key / Groq API key — saved locally in config.json and "
                "masked in the UI.\n",
            ),
            (
                "body",
                "LM Studio base URL (Local) — LM Studio server address (default "
                "http://127.0.0.1:1234).\n",
            ),
            (
                "body",
                "ComfyUI base URL / Forge Neo base URL — used only when unloading "
                "external VRAM during a Local pre-flight.\n",
            ),
            (
                "body",
                "Save Settings — saves keys, URLs, selected engines/models, and "
                "the current tab selections.\n",
            ),
            (
                "body",
                "Saved model profiles — lists profiles saved per engine, model, "
                "and tab; Delete removes the selected one after confirmation.\n",
            ),
            (
                "body",
                "Add a camera / lens — adds the typed entry to the Generator's "
                "camera list (existing entries are selected on the Generator tab).\n",
            ),
            (
                "body",
                "Text System Prompts — choose or type a name, edit the text, and "
                "Save / Create Prompt writes that name to the system_prompts "
                "folder; Delete Prompt removes it after confirmation. Names allow "
                "letters, numbers, spaces, dots, underscores, and hyphens.\n",
            ),
            (
                "body",
                "Vision System Prompts — the same editor for the Image to Prompt "
                "prompts.\n",
            ),
            (
                "body",
                "Character / LoRA Management — name, exact trigger words, and "
                "character description; Save LoRA creates or updates it, Delete "
                "LoRA removes it. Selecting None as Character / LoRA skips these "
                "rules.\n",
            ),
            (
                "body",
                "Reset / Delete All Personal Data — permanently deletes settings "
                "and model profiles, LoRA profiles, camera entries, custom system "
                "prompt .txt files, history entries, the saved rough idea, and "
                "cached model lists. The 3 baseline prompts (single_prompt, "
                "multi_prompt, image_to_prompt) are restored; saved API keys are "
                "deleted only when the checkbox is enabled.\n\n",
            ),
            ("heading", "History tab\n"),
            (
                "body",
                "Search — filters the saved prompts and rough ideas as you type; "
                "up to 200 newest matches are listed.\n",
            ),
            (
                "body",
                "Show Favorites Only — restricts the list to favorited entries.\n",
            ),
            (
                "body",
                "Export Favorites — writes every favorite prompt to a text file "
                "you choose.\n",
            ),
            (
                "body",
                "Past generations — newest first; hovering shows the rough idea; "
                "click to load an entry into the detail panes.\n",
            ),
            (
                "body",
                "Generated Prompts / Original Idea — the saved prompt and the "
                "idea you typed.\n",
            ),
            (
                "body",
                "Load back to Generator — puts the original idea into the "
                "Generator and clears its output.\n",
            ),
            (
                "body",
                "Toggle Favorite (★) — marks or unmarks the selected entry.\n",
            ),
            ("body", "Copy Prompt — copies the selected generated prompt.\n"),
            (
                "body",
                "Delete Selected — permanently deletes the selected entry after "
                "confirmation.\n",
            ),
            (
                "body",
                "Bulk Delete — opens a dialog to delete many entries at once. "
                "Favorites are kept unless you include them, an optional age "
                "cutoff can limit deletion, and the dialog shows how many "
                "entries will be removed before you confirm.\n",
            ),
        ]
        return entries

    def _open_kofi(self, _event=None):
        return open_external_url(KOFI_URL)

    def _fit_help_intro_height(self, event=None):
        raw = self.help_intro_text._textbox
        try:
            pixels = raw.count("1.0", "end", "ypixels")
            current = int(float(self.help_intro_text.cget("height")))
        except (tkinter.TclError, TypeError, ValueError):
            return
        if not pixels:
            return
        needed = max(150, int(pixels[0]) + 10)
        # Keep the scrollable guide usable: the intro may scroll when its full
        # text would take more than about half of the tab height.
        try:
            cap = max(150, int(int(self.help_tabview.winfo_height()) * 0.55))
            needed = min(needed, cap)
        except (tkinter.TclError, TypeError, ValueError):
            pass
        if abs(needed - current) <= 2:
            return
        try:
            self.help_intro_text.configure(height=needed)
        except tkinter.TclError:
            pass

    def _insert_help_entries(self, entries, textbox):
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        raw = textbox._textbox
        raw.tag_configure("title", font=("Segoe UI", 21, "bold"))
        raw.tag_configure("muted", font=("Segoe UI", 11), foreground="gray")
        raw.tag_configure(
            "heading",
            font=("Segoe UI", 15, "bold"),
            spacing1=12,
            spacing3=3,
        )
        raw.tag_configure("body", spacing3=2)
        for index, (tag, value) in enumerate(entries):
            if tag != "link":
                textbox.insert("end", value, tag)
                continue
            _name, url = value
            link_tag = f"link_{index}"
            textbox.insert("end", url, link_tag)
            raw.tag_configure(
                link_tag, foreground=LINK_COLOR, underline=True
            )
            raw.tag_bind(
                link_tag,
                "<Button-1>",
                lambda _event, link=url: open_external_url(link),
            )
            raw.tag_bind(
                link_tag,
                "<Enter>",
                lambda _event: raw.configure(cursor="hand2"),
            )
            raw.tag_bind(
                link_tag,
                "<Leave>",
                lambda _event: raw.configure(cursor="xterm"),
            )
        textbox.see("1.0")
