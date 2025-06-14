import customtkinter as ctk
from tkinter import filedialog, simpledialog, messagebox
import os
import shutil
from datetime import datetime
import subprocess
import json
import re
import webbrowser
import time
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import threading
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def ensure_client_secrets():
    if not os.path.exists("client_secrets.json"):
        shutil.copy(resource_path("client_secrets.json"), "client_secrets.json")

# === Constants & Globals ===
CONFIG_FILE = "fl_config.json"
upload_mode = False
selected_beats_for_upload = set()
selected_folder = None
selected_version = None
beats_data_cache = {}

# === Helper/Data Functions ===
def get_fl_studio_path():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            fl_path = config.get("fl_studio_path", "")
            if os.path.exists(fl_path):
                return fl_path
    return None

def prompt_and_save_fl_path():
    fl_path = filedialog.askopenfilename(title="Select FL Studio Executable", filetypes=[("Executable Files", "*.exe")])
    if fl_path:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"fl_studio_path": fl_path}, f)
        return fl_path
    return None

def get_beat_folders():
    if not os.path.exists("backups"):
        os.makedirs("backups")
    return [folder for folder in os.listdir("backups") if os.path.isdir(os.path.join("backups", folder))]

def extract_timestamp(filename):
    match = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})", filename)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M")
        except ValueError:
            return datetime.min
    return datetime.min

def get_versions_for_beat(beat_folder):
    folder_path = os.path.join("backups", beat_folder)
    flps = [f for f in os.listdir(folder_path) if f.endswith(".flp")]
    present_version = None
    timestamped_versions = []
    for f in flps:
        if re.match(rf"^{re.escape(beat_folder)}\.flp$", f):
            present_version = f
        else:
            timestamped_versions.append(f)
    timestamped_versions.sort(key=extract_timestamp, reverse=True)
    if present_version:
        return [present_version] + timestamped_versions
    else:
        return timestamped_versions

def get_notes_for_version(beat_folder, version_file):
    note_file = version_file.replace(".flp", ".txt")
    note_path = os.path.join("backups", beat_folder, note_file)
    if os.path.exists(note_path):
        with open(note_path, "r") as f:
            return f.read()
    return ""

def open_in_fl(folder, version_file):
    fl_path = get_fl_studio_path()
    if not fl_path:
        fl_path = prompt_and_save_fl_path()
        if not fl_path:
            return
    flp_path = os.path.abspath(os.path.join("backups", folder, version_file))
    if os.path.exists(flp_path):
        subprocess.Popen([fl_path, flp_path])

def create_new_project():
    project_name = ctk.CTkInputDialog(text="Enter new project name:", title="🎵 New Project").get_input()
    if not project_name:
        return
    fl_path = get_fl_studio_path()
    if not fl_path:
        fl_path = prompt_and_save_fl_path()
        if not fl_path:
            return
    beat_folder = os.path.join("backups", project_name)
    os.makedirs(beat_folder, exist_ok=True)
    new_flp_path = os.path.join(beat_folder, f"{project_name}.flp")
    shutil.copy2(resource_path("empty_template.flp"), new_flp_path)
    if messagebox.askyesno("Add Notes?", "Do you want to add notes for this new project?"):
        def save_notes(notes):
            note_path = os.path.join(beat_folder, f"{project_name}.txt")
            with open(note_path, "w") as f:
                f.write(notes if notes else "(No notes)")
            refresh_all()
        themed_note_popup(save_notes)
    subprocess.Popen([fl_path, os.path.abspath(new_flp_path)])
    refresh_all()

def create_new_backup(folder):
    if not folder:
        return
    present_flp = os.path.join("backups", folder, f"{folder}.flp")
    if not os.path.exists(present_flp):
        messagebox.showerror("Error", "No present version found to back up.")
        return
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    backup_name = f"{folder}_{timestamp}.flp"
    backup_path = os.path.join("backups", folder, backup_name)
    shutil.copy2(present_flp, backup_path)
    def save_notes(notes):
        note_path = os.path.join("backups", folder, f"{folder}_{timestamp}.txt")
        with open(note_path, "w") as f:
            f.write(notes if notes else "")
        refresh_all()
    if messagebox.askyesno("Add Notes?", "Do you want to add notes for this backup version?"):
        themed_note_popup(save_notes)
    else:
        refresh_all()

def toggle_selected_beat(folder_name):
    if folder_name in selected_beats_for_upload:
        selected_beats_for_upload.remove(folder_name)
    else:
        selected_beats_for_upload.add(folder_name)
    if len(selected_beats_for_upload) > 0:
        upload_selected_btn.configure(state="normal")
    else:
        upload_selected_btn.configure(state="disabled")

def upload_selected_to_gdrive():
    if not selected_beats_for_upload:
        messagebox.showinfo("No Selection", "Please select at least one beat to upload.")
        return
    upload_selected_btn.configure(state="disabled", text="Connecting to Drive...")
    def do_drive_folder():
        try:
            ensure_client_secrets()
            gauth = GoogleAuth()
            gauth.LocalWebserverAuth()
            drive = GoogleDrive(gauth)
            folder_list = drive.ListFile({
                'q': "mimeType='application/vnd.google-apps.folder' and trashed=false and title='FLowTrack Projects'"
            }).GetList()
            if folder_list:
                flowtrack_folder = folder_list[0]
            else:
                flowtrack_folder = drive.CreateFile({
                    'title': 'FLowTrack Projects',
                    'mimeType': 'application/vnd.google-apps.folder'
                })
                flowtrack_folder.Upload()
            flowtrack_folder_id = flowtrack_folder['id']
            all_files = []
            for beat_folder in selected_beats_for_upload:
                local_folder = os.path.join("backups", beat_folder)
                for root, _, files in os.walk(local_folder):
                    for file in files:
                        if re.match(r"^Backup.*\(overwritten at \d{1,2}h\d{2}\)", file):
                            continue
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, local_folder)
                        all_files.append((beat_folder, file_path, rel_path))
            total_files = len(all_files)
            app.after(0, lambda: (
                progress_bar.set(0),
                progress_bar.pack(pady=(0, 10)),
                upload_selected_btn.configure(text=f"Uploading: 0/{total_files}")
            ))
            uploaded = 0
            for beat_folder, file_path, rel_path in all_files:
                subfolder_list = drive.ListFile({
                    'q': f"'{flowtrack_folder_id}' in parents and trashed=false and title='{beat_folder}' and mimeType='application/vnd.google-apps.folder'"
                }).GetList()
                if subfolder_list:
                    beat_drive_folder = subfolder_list[0]
                else:
                    beat_drive_folder = drive.CreateFile({
                        'title': beat_folder,
                        'parents': [{'id': flowtrack_folder_id}],
                        'mimeType': 'application/vnd.google-apps.folder'
                    })
                    beat_drive_folder.Upload()
                beat_drive_folder_id = beat_drive_folder['id']
                gfile = drive.CreateFile({
                    'title': rel_path,
                    'parents': [{'id': beat_drive_folder_id}]
                })
                gfile.SetContentFile(file_path)
                gfile.Upload()
                uploaded += 1
                app.after(0, lambda u=uploaded: (
                    progress_bar.set(u / total_files),
                    upload_selected_btn.configure(text=f"Uploading: {u}/{total_files}")
                ))
            app.after(0, lambda: (
                progress_bar.set(1),
                messagebox.showinfo("Upload Complete", "All selected beats have been uploaded!"),
                progress_bar.pack_forget()
            ))
        except Exception as e:
            app.after(0, lambda err=e: (
                messagebox.showerror("Google Drive Error", str(err)),
                progress_bar.pack_forget()
            ))
        finally:
            app.after(0, lambda: upload_selected_btn.configure(state="normal", text="⬆️ Upload Selected"))
            app.after(0, exit_upload_mode)
    threading.Thread(target=do_drive_folder, daemon=True).start()

def load_all_beats_data():
    data = {}
    for beat in get_beat_folders():
        versions = get_versions_for_beat(beat)
        notes = {}
        for v in versions:
            notes[v.lower()] = get_notes_for_version(beat, v).lower()
        present_beat_file = f"{beat}.flp"
        notes[present_beat_file.lower()] = get_notes_for_version(beat, present_beat_file).lower()
        data[beat] = {
            "versions": [v.lower() for v in versions] + [present_beat_file.lower()],
            "notes": notes,
        }
    return data

def filter_beats(query):
    query = query.lower()
    filtered_beats = []
    for beat, info in beats_data_cache.items():
        if query in beat.lower():
            filtered_beats.append(beat)
            continue
        if any(query in v for v in info["versions"]):
            filtered_beats.append(beat)
            continue
        if any(query in note for note in info["notes"].values()):
            filtered_beats.append(beat)
            continue
    return filtered_beats

def filter_versions(folder, query):
    query = query.lower()
    all_versions = get_versions_for_beat(folder)
    filtered_versions = []
    for v in all_versions:
        v_lower = v.lower()
        notes = get_notes_for_version(folder, v).lower()
        if query in v_lower or query in notes:
            filtered_versions.append(v)
    return filtered_versions

# === UI Update Functions ===
def refresh_all():
    load_folders()
    refresh_versions()
    refresh_notes("")
    # Fix: Only select folder if it still exists
    global selected_folder
    if selected_folder and os.path.exists(os.path.join("backups", selected_folder)):
        on_folder_select(selected_folder)
    else:
        selected_folder = None
        update_versions_list(None)
        refresh_notes("")

def refresh_versions():
    version_listbox.grid_forget()
    version_listbox.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
    version_listbox.update_idletasks()

def refresh_notes(content):
    note_display.configure(state="normal")
    note_display.delete("1.0", "end")
    note_display.insert("1.0", content)
    note_display.configure(state="normal")

def update_folder_list(filtered_beats=None):
    for widget in folder_listbox.winfo_children():
        widget.destroy()
    beats_to_show = filtered_beats if filtered_beats is not None else get_beat_folders()
    for folder in beats_to_show:
        folder_row = ctk.CTkFrame(folder_listbox, fg_color="transparent")
        folder_row.pack(fill="x", padx=5, pady=2)
        if upload_mode:
            folder_row.grid_columnconfigure(0, weight=0)
            folder_row.grid_columnconfigure(1, weight=1)
            var = ctk.BooleanVar(value=folder in selected_beats_for_upload)
            def make_toggle(folder_name):
                return lambda: (toggle_selected_beat(folder_name), update_folder_list())
            checkbox = ctk.CTkCheckBox(
                folder_row,
                text="",
                variable=var,
                width=24,
                command=make_toggle(folder)
            )
            checkbox.grid(row=0, column=0, padx=(2, 6), sticky="w")
            btn = ctk.CTkButton(
                folder_row, text=folder, width=180, anchor="w",
                font=("Bahnschrift", 12),
                state="disabled"
            )
            btn.grid(row=0, column=1, sticky="ew", padx=(0, 2))
        else:
            btn = ctk.CTkButton(folder_row, text=folder, width=180, anchor="w",
                                font=("Bahnschrift", 12),
                                command=lambda f=folder: on_folder_select(f))
            btn.pack(side="left", fill="x", expand=True, padx=(5, 2))
            delete_btn = ctk.CTkButton(folder_row,
                text="🗑",
                width=26,
                height=26,
                font=("Segoe UI Symbol", 13),
                fg_color="#922",
                hover_color="#b33",
                corner_radius=6,
                anchor="center",
                command=lambda f=folder: confirm_delete_folder(f)
            )
            delete_btn.pack(side="right", padx=(4, 4), pady=2)

def update_versions_list(folder, filtered_versions=None):
    for widget in version_listbox.winfo_children():
        widget.destroy()
    if not folder:
        return
    versions_to_show = filtered_versions if filtered_versions is not None else get_versions_for_beat(folder)
    for version_file in versions_to_show:
        version_row = ctk.CTkFrame(version_listbox, fg_color="transparent")
        version_row.pack(fill="x", padx=5, pady=2)
        is_present_version = version_file == f"{folder}.flp"
        btn = ctk.CTkButton(
            version_row,
            text=version_file,
            font=("Bahnschrift", 12),
            anchor="w",
            fg_color="#2F8A3E" if is_present_version else None,
            hover_color="#1b632d" if is_present_version else None,
            command=lambda f=version_file: on_version_select(folder, f)
        )
        btn.pack(side="left", fill="x", expand=True, padx=(5, 2))
        btn.bind("<Double-Button-1>", lambda event, f=version_file: open_in_fl(folder, f))
        if not is_present_version:
            revert_btn = ctk.CTkButton(
                version_row,
                text="↩",
                width=26,
                height=26,
                font=("Segoe UI Symbol", 13),
                fg_color="#D4AF37",
                hover_color="#B8860B",
                corner_radius=6,
                command=lambda f=version_file: confirm_revert_version(folder, f)
            )
            revert_btn.pack(side="left", padx=(2, 1))
            delete_btn = ctk.CTkButton(
                version_row,
                text="🗑",
                width=26,
                height=26,
                font=("Segoe UI Symbol", 13),
                fg_color="#922",
                hover_color="#b33",
                corner_radius=6,
                command=lambda f=version_file: confirm_delete_version(folder, f)
            )
            delete_btn.pack(side="right", padx=(1, 5))

def load_folders():
    global beats_data_cache
    beats_data_cache = load_all_beats_data()
    update_folder_list()

def confirm_delete_folder(folder):
    if messagebox.askyesno("Delete Project", f"Are you sure you want to delete '{folder}' and all its versions?"):
        shutil.rmtree(os.path.join("backups", folder))
        refresh_all()

def confirm_delete_version(folder, version_file):
    if messagebox.askyesno("Delete Version", f"Delete version '{version_file}' and its notes?"):
        os.remove(os.path.join("backups", folder, version_file))
        txt_file = version_file.replace(".flp", ".txt")
        txt_path = os.path.join("backups", folder, txt_file)
        if os.path.exists(txt_path):
            os.remove(txt_path)
        on_folder_select(folder)

def confirm_revert_version(folder, version_file):
    answer = messagebox.askyesno(
        "Revert to this version",
        f"Are you sure you want to revert the current version of '{folder}' to this backup?"
    )
    if answer:
        try:
            backup_path = os.path.join("backups", folder, version_file)
            present_path = os.path.join("backups", folder, f"{folder}.flp")
            shutil.copy2(backup_path, present_path)
            messagebox.showinfo("Revert Successful", "The project has been reverted to the selected backup.")
            on_folder_select(folder)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to revert version:\n{e}")

# === Event Handlers ===
def on_folder_select(folder):
    global selected_folder, selected_version
    selected_folder = folder
    selected_version = None
    update_versions_list(folder)
    refresh_notes("")
    versions_search_var.set("")
    if folder:
        create_backup_btn.configure(state="normal")
    else:
        create_backup_btn.configure(state="disabled")

def on_version_select(folder, version_file):
    global selected_version
    selected_version = (folder, version_file)
    notes = get_notes_for_version(folder, version_file)
    note_display.configure(state="normal")
    note_display.delete("1.0", "end")
    note_display.insert("1.0", notes)
    note_display.configure(state="disabled")
    edit_note_btn.configure(state="normal")
    save_note_btn.configure(state="normal")

def enable_note_edit():
    note_display.configure(state="normal")

def save_note_edits():
    if not selected_version:
        return
    folder, version_file = selected_version
    note_path = os.path.join("backups", folder, version_file.replace(".flp", ".txt"))
    with open(note_path, "w") as f:
        content = note_display.get("1.0", "end").strip()
        f.write(content)
    note_display.configure(state="disabled")
    save_note_btn.configure(text="✅ Saved!", fg_color="#2ea043", hover=False)
    app.after(2000, lambda: save_note_btn.configure(text="💾 Save", fg_color=original_save_fg, hover=True))
    refresh_all()

def on_beats_search(*args):
    query = beats_search_var.get().strip()
    if not query:
        update_folder_list()
    else:
        filtered = filter_beats(query)
        update_folder_list(filtered)
        update_versions_list(None)
        refresh_notes("")

def on_versions_search(*args):
    query = versions_search_var.get().strip()
    if not selected_folder:
        return
    if not query:
        update_versions_list(selected_folder)
    else:
        filtered_versions = filter_versions(selected_folder, query)
        update_versions_list(selected_folder, filtered_versions)
        refresh_notes("")

# === UI Layout ===
ctk.set_appearance_mode("dark")
app = ctk.CTk()
app.title("FLowTrack")
app.geometry("1000x600")
app.minsize(1000, 600)
app.configure(fg_color="#1e1e1e")
app.iconbitmap(resource_path("flowtrack_icon.ico"))

main_frame = ctk.CTkFrame(app)
main_frame.pack(expand=True, fill="both", padx=15, pady=15)
main_frame.grid_columnconfigure(0, weight=2, uniform="group")
main_frame.grid_columnconfigure(1, weight=3, uniform="group")
main_frame.grid_columnconfigure(2, weight=2, uniform="group")
main_frame.grid_rowconfigure(0, weight=1)
main_frame.grid_rowconfigure(1, weight=0)

folder_listbox = ctk.CTkScrollableFrame(main_frame, label_text="🎵 Beats", label_font=("Bahnschrift", 14, "bold"))
folder_listbox.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
beats_search_var = ctk.StringVar()
beats_search_entry = ctk.CTkEntry(
    main_frame,
    placeholder_text="Search Beats...",
    placeholder_text_color="#888888",
    textvariable=beats_search_var
)
beats_search_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(5, 10))

version_listbox = ctk.CTkScrollableFrame(main_frame, label_text="🕓 Versions", label_font=("Bahnschrift", 14, "bold"))
version_listbox.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
versions_search_var = ctk.StringVar()
versions_search_entry = ctk.CTkEntry(main_frame, placeholder_text="Search Versions...", textvariable=versions_search_var)
versions_search_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(5, 10))

note_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
note_frame.grid(row=0, column=2, sticky="nsew", padx=(0, 0), pady=(0, 0))
note_frame.grid_rowconfigure(1, weight=1)
note_frame.grid_columnconfigure(0, weight=1)
note_label = ctk.CTkLabel(
    note_frame,
    text="📝 Notes",
    font=("Bahnschrift", 14, "bold"),
    anchor="center",
    fg_color="#3B3B3B",
    text_color="#fff",
    corner_radius=8,
    height=28,
    width=180
)
note_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 0))
note_display = ctk.CTkTextbox(note_frame, wrap="word")
note_display.grid(row=1, column=0, sticky="nsew", padx=10, pady=(10, 10))
note_display.configure(state="disabled")

note_buttons_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
note_buttons_frame.grid(row=1, column=2, sticky="ew", pady=(5, 10), padx=(0, 0))
note_buttons_frame.grid_columnconfigure(0, weight=1)
note_buttons_frame.grid_columnconfigure(1, weight=1)
edit_note_btn = ctk.CTkButton(
    note_buttons_frame,
    text="Edit",
    width=140,
    height=28,
    font=("Bahnschrift", 13, "bold")
)
save_note_btn = ctk.CTkButton(
    note_buttons_frame,
    text="💾 Save",
    width=140,
    height=28,
    font=("Bahnschrift", 13, "bold")
)
edit_note_btn.grid(row=0, column=0, padx=5, pady=0, sticky="ew")
save_note_btn.grid(row=0, column=1, padx=5, pady=0, sticky="ew")
edit_note_btn.configure(state="disabled")
save_note_btn.configure(state="disabled")
original_save_fg = save_note_btn.cget("fg_color")
edit_note_btn.configure(command=enable_note_edit)
save_note_btn.configure(command=save_note_edits)

# --- Upload Section ---
def themed_note_popup(callback):
    popup = ctk.CTkToplevel(app)
    popup.title("📝 Add Notes")
    popup.geometry("400x250")
    popup.configure(fg_color="#2a2a2a")
    popup.grab_set()
    label = ctk.CTkLabel(popup, text="Enter notes:", font=("Bahnschrift", 14))
    label.pack(pady=(20, 10))
    text_box = ctk.CTkTextbox(popup, height=100)
    text_box.pack(padx=20, fill="both", expand=True)
    def submit():
        notes = text_box.get("1.0", "end").strip()
        popup.destroy()
        callback(notes)
    submit_btn = ctk.CTkButton(popup, text="Save Notes", command=submit)
    submit_btn.pack(pady=15)

def upload_flp():
    flp_path = filedialog.askopenfilename(filetypes=[("FL Studio Project", "*.flp")])
    if not flp_path:
        return
    filename = os.path.basename(flp_path)
    beat_name = os.path.splitext(filename)[0]
    beat_folder = os.path.join("backups", beat_name)
    os.makedirs(beat_folder, exist_ok=True)
    present_flp_path = os.path.join(beat_folder, f"{beat_name}.flp")
    if not os.path.exists(present_flp_path):
        shutil.copy2(flp_path, present_flp_path)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    new_flp_name = f"{beat_name}_{timestamp}.flp"
    new_flp_path = os.path.join(beat_folder, new_flp_name)
    shutil.copy2(flp_path, new_flp_path)
    def save_notes(notes):
        note_path = os.path.join(beat_folder, f"{beat_name}_{timestamp}.txt")
        with open(note_path, "w") as f:
            f.write(notes if notes else "")
        refresh_all()
    themed_note_popup(save_notes)

def scan_for_flps():
    popup = ctk.CTkToplevel(app)
    popup.title("Scan Source")
    popup.geometry("500x160")
    popup.grab_set()
    ctk.CTkLabel(popup, text="Where do you want to import from?", font=("Bahnschrift", 13)).pack(pady=(18, 8))
    def from_drive():
        popup.destroy()
        try:
            gauth = GoogleAuth()
            gauth.LocalWebserverAuth()
            drive = GoogleDrive(gauth)
            folder_list = drive.ListFile({
                'q': "mimeType='application/vnd.google-apps.folder' and trashed=false and title='FLowTrack Projects'"
            }).GetList()
            if not folder_list:
                messagebox.showinfo("Not Found", "No 'FLowTrack Projects' folder found in your Google Drive.")
                return
            flowtrack_folder = folder_list[0]
            flowtrack_folder_id = flowtrack_folder['id']
            beat_folders = drive.ListFile({
                'q': f"'{flowtrack_folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'"
            }).GetList()
            imported = 0
            for beat_folder in beat_folders:
                beat_name = beat_folder['title']
                beat_folder_id = beat_folder['id']
                beat_files = drive.ListFile({
                    'q': f"'{beat_folder_id}' in parents and trashed=false"
                }).GetList()
                local_beat_folder = os.path.join("backups", beat_name)
                os.makedirs(local_beat_folder, exist_ok=True)
                for file in beat_files:
                    if file['title'].endswith('.flp') or file['title'].endswith('.txt'):
                        local_path = os.path.join(local_beat_folder, file['title'])
                        file.GetContentFile(local_path)
                        imported += 1
            messagebox.showinfo("Scan Complete", f"Imported {imported} files from Google Drive.")
            refresh_all()
        except Exception as e:
            messagebox.showerror("Google Drive Error", str(e))
    def from_local():
        popup.destroy()
        folder = filedialog.askdirectory(title="Select Folder to Scan for .flp Files")
        if not folder:
            return
        def scan_task():
            try:
                found_flps = []
                found_notes = {}
                for root, _, files in os.walk(folder):
                    for file in files:
                        if file.endswith(".flp"):
                            found_flps.append(os.path.join(root, file))
                        elif file.endswith(".txt"):
                            found_notes[file] = os.path.join(root, file)
                if not found_flps:
                    app.after(0, lambda: messagebox.showinfo("Scan Complete", "No .flp files found in selected folder."))
                    return
                for flp_path in found_flps:
                    filename = os.path.basename(flp_path)
                    beat_name = os.path.splitext(filename)[0]
                    beat_folder = os.path.join("backups", beat_name)
                    os.makedirs(beat_folder, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
                    new_flp_name = f"{beat_name}_{timestamp}.flp"
                    new_flp_path = os.path.join(beat_folder, new_flp_name)
                    shutil.copy2(flp_path, new_flp_path)
                    note_filename = filename.replace(".flp", ".txt")
                    note_path = os.path.join(beat_folder, new_flp_name.replace(".flp", ".txt"))
                    if note_filename in found_notes:
                        shutil.copy2(found_notes[note_filename], note_path)
                    else:
                        with open(note_path, "w") as f:
                            f.write("(Scanned version - no notes)")
                app.after(0, lambda: messagebox.showinfo("Scan Complete", f"Added {len(found_flps)} FLP files to your project backups!"))
                app.after(0, refresh_all)
            except Exception as e:
                app.after(0, lambda: messagebox.showerror("Scan Error", f"An error occurred during scan:\n{e}"))
        threading.Thread(target=scan_task, daemon=True).start()
    btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
    btn_frame.pack(pady=18)
    ctk.CTkButton(btn_frame, text="☁️Import from Google Drive", command=from_drive, width=180, font=("Bahnschrift", 13)).pack(side="left", padx=8)
    ctk.CTkButton(btn_frame, text="📂 Choose from local files", command=from_local, width=180, font=("Bahnschrift", 13)).pack(side="left", padx=8)
    popup.protocol("WM_DELETE_WINDOW", popup.destroy)

button_bar = ctk.CTkFrame(app, fg_color="transparent")
button_bar.pack(pady=(0, 15))
create_btn = ctk.CTkButton(button_bar, text="✨ Create New Project", font=("Bahnschrift", 13), command=create_new_project)
create_btn.grid(row=0, column=0, padx=10)
upload_btn = ctk.CTkButton(button_bar, text="📤 Upload .flp Project", font=("Bahnschrift", 13), command=upload_flp)
upload_btn.grid(row=0, column=1, padx=10)
scan_btn = ctk.CTkButton(button_bar, text="📂 Scan Folder", font=("Bahnschrift", 13), command=scan_for_flps)
scan_btn.grid(row=0, column=2, padx=10)
progress_bar = ctk.CTkProgressBar(app, width=400)
progress_bar.pack(pady=(0, 10))
progress_bar.set(0)
progress_bar.pack_forget()

def enter_upload_mode():
    global upload_mode
    upload_mode = True
    selected_beats_for_upload.clear()
    update_folder_list()
    upload_gdrive_btn.grid_remove()
    cancel_upload_btn.grid(row=0, column=4, padx=10)
    upload_selected_btn.grid(row=0, column=5, padx=10)
    upload_selected_btn.configure(state="disabled")

def exit_upload_mode():
    global upload_mode
    upload_mode = False
    selected_beats_for_upload.clear()
    update_folder_list()
    cancel_upload_btn.grid_remove()
    upload_selected_btn.grid_remove()
    upload_gdrive_btn.grid(row=0, column=4, padx=10)

upload_gdrive_btn = ctk.CTkButton(
    button_bar,
    text="☁️ Upload to Google Drive",
    font=("Bahnschrift", 13),
    command=enter_upload_mode
)
upload_gdrive_btn.grid(row=0, column=4, padx=10)
cancel_upload_btn = ctk.CTkButton(
    button_bar,
    text="❌ Cancel",
    font=("Bahnschrift", 13),
    fg_color="#922",
    hover_color="#b33",
    width=90,
    command=exit_upload_mode
)
upload_selected_btn = ctk.CTkButton(
    button_bar,
    text="⬆️ Upload Selected",
    font=("Bahnschrift", 13),
    state="disabled",
    width=130,
    command=upload_selected_to_gdrive
)
create_backup_btn = ctk.CTkButton(
    button_bar,
    text="🧩 Create New Backup",
    font=("Bahnschrift", 13),
    state="disabled",
    command=lambda: create_new_backup(selected_folder)
)
create_backup_btn.grid(row=0, column=3, padx=10)

# --- Bindings ---
beats_search_var.trace_add("write", on_beats_search)
versions_search_var.trace_add("write", on_versions_search)

# --- Main ---
load_folders()
app.mainloop()