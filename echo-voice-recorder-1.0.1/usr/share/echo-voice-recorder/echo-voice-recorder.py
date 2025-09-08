#!/usr/bin/env python3

import sys
import os
import pyaudio
import wave
import time
import shutil
import json
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QHBoxLayout, QAction, QMenu, QMessageBox, QAbstractItemView, QFileDialog, QInputDialog
from PyQt5.QtGui import QMovie, QPixmap, QFont, QIcon, QFontDatabase
from PyQt5.QtCore import QSize, Qt, QDir, QEvent, QFileInfo, QThread, pyqtSignal
from pydub import AudioSegment

def resource_path(relative_path):
    """
    Geliştirme ortamı ve Linux sistemi kurulumu için kaynak dosyalarının yolunu belirler.
    """
    # 1. Linux sistemi için standart /usr/share dizinini kontrol et.
    #    Bu, program .deb paketi olarak kurulduğunda kullanılacak yoldur.
    system_path = os.path.join("/usr/share/echo-voice-recorder", relative_path)
    if os.path.exists(system_path):
        return system_path

    # 2. Geliştirme ortamı için mevcut dosyanın dizinini kullan.
    #    Bu, programı doğrudan geliştirme klasöründen çalıştırdığında kullanılacak yoldur.
    dev_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)
    if os.path.exists(dev_path):
        return dev_path

    return None

class PlaybackThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, audio_data, parent=None):
        super().__init__(parent)
        self.audio_data = audio_data
        self.p = pyaudio.PyAudio()
        self.is_playing = True

    def run(self):
        try:
            with wave.open(self.audio_data['path'], 'rb') as wf:
                stream = self.p.open(format=self.p.get_format_from_width(wf.getsampwidth()),
                                     channels=wf.getnchannels(),
                                     rate=wf.getframerate(),
                                     output=True)

                chunk_size = 1024
                data = wf.readframes(chunk_size)
                while data and self.is_playing:
                    stream.write(data)
                    data = wf.readframes(chunk_size)

                stream.stop_stream()
                stream.close()
            self.finished.emit()
        except Exception as e:
            self.error.emit(f"Oynatma sırasında bir hata oluştu: {e}")

class SoundRecorderApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.button_path = resource_path("icons")
        self.record_path = os.path.expanduser("~")
        self.config_dir = os.path.join(os.path.expanduser("~"), ".EchoVoiceRecorder")
        self.config_file = os.path.join(self.config_dir, "userdata.json")
        self.languages_dir = resource_path("languages")

        self.system_on = False
        self.mic_on = False
        self.record_format = ".WAV"
        self.current_language = "tr"
        self.translations = {}
        
        self.load_settings()
        self.load_translations()
        
        self.setWindowTitle(self.translations.get("window_title", "Echo Ses Kaydedici"))
        self.setFixedSize(360, 360)
        self.setStyleSheet("background-color: #363636;")

        icon_path = resource_path("icons/recicon.png")
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.is_paused = False
        self.is_recording = False
        self.record_counter = 0

        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 44100
        self.CHUNK = 1024
        self.frames = []
        self.p = pyaudio.PyAudio()
        self.stream = None
        
        self.start_time = None
        self.playback_thread = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        top_section = QVBoxLayout()
        top_buttons_and_gif_layout = QHBoxLayout()
        left_buttons_layout = QVBoxLayout()
        
        self.system_button = self.create_styled_button("system", "system_button")
        self.mic_button = self.create_styled_button("mic", "mic_button")         
        
        left_buttons_layout.addWidget(self.system_button)
        left_buttons_layout.addWidget(self.mic_button)
        
        top_buttons_and_gif_layout.addLayout(left_buttons_layout)
        
        self.display_container = QWidget()
        self.display_container.setFixedSize(285, 60)
        self.display_container.setStyleSheet("background-color: #6a695a; border: 2px solid #585858;")
        
        self.status_label = QLabel(self.display_container)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("background-color: transparent; color: #333333;")

        font_path = resource_path("fonts/AlphaSmart3000.ttf")
        if font_path and os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    self.status_label.setFont(QFont(font_families[0], 12))

        self.status_label.setFixedSize(self.display_container.size())
        
        self.flare_label = QLabel(self.display_container)
        flare_path = resource_path("icons/flare.png")
        if flare_path and os.path.exists(flare_path):
            flare_pixmap = QPixmap(flare_path)
            self.flare_label.setPixmap(flare_pixmap.scaled(self.display_container.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.flare_label.setFixedSize(self.display_container.size())
        self.flare_label.lower() 
        
        top_buttons_and_gif_layout.addWidget(self.display_container)
        top_section.addLayout(top_buttons_and_gif_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        top_section.addLayout(buttons_layout)

        self.create_buttons(buttons_layout)
        
        self.table_widget = QTableWidget()
        self.setup_table()

        main_layout.addLayout(top_section)
        main_layout.addWidget(self.table_widget)
        
        self.create_menu_bar()

        self._update_status_display()
        self.play_button.clicked.connect(self.play_recording)
        
        self.system_button.clicked.connect(self.toggle_system_sound)
        self.mic_button.clicked.connect(self.toggle_microphone)


    def __del__(self):
        self.p.terminate()

    def load_translations(self):
        """Ayarlanan dile göre çeviri dosyasını yükler."""
        lang_file_path = resource_path(f"languages/{self.current_language}.json")
        try:
            if lang_file_path and os.path.exists(lang_file_path):
                with open(lang_file_path, 'r', encoding='utf-8') as f:
                    self.translations = json.load(f)
            else:
                raise FileNotFoundError(f"'{lang_file_path}' dosyası bulunamadı.")
        except (IOError, json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Çeviri dosyası yüklenirken hata oluştu: {e}. Varsayılan dile geçiliyor.")
            self.translations = {} # Hata olursa boş sözlük kullan

    def load_settings(self):
        """Uygulama ayarlarını dosyadan yükler."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    settings = json.load(f)
                    self.record_format = settings.get("record_format", self.record_format)
                    self.current_language = settings.get("language", self.current_language)
            except (IOError, json.JSONDecodeError) as e:
                print(f"Ayarlar dosyası yüklenirken hata oluştu: {e}")
                self.save_settings()
        else:
            self.save_settings()

    def save_settings(self):
        """Uygulama ayarlarını dosyaya kaydeder."""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
        
        settings = {
            "record_format": self.record_format,
            "language": self.current_language
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except IOError as e:
            print(f"Ayarlar dosyası kaydedilirken hata oluştu: {e}")

    def _update_status_display(self, current_status="status_ready"):
        system_status = self.translations.get("system_on", "on") if self.system_on else self.translations.get("system_off", "off")
        mic_status = self.translations.get("mic_on", "on") if self.mic_on else self.translations.get("mic_off", "off")
        
        display_text = (
            f"{self.translations.get(current_status, current_status)}\n"
            f"System: {system_status} | Mic: {mic_status}\n"
            f"Format: {self.record_format}"
        )
        self.status_label.setText(display_text)
        self.status_label.setAlignment(Qt.AlignCenter)

    def toggle_system_sound(self):
        self.system_on = not self.system_on
        self._update_status_display()
        self.update_toggle_button_style(self.system_button, "system", self.system_on)
        print(f"Sistem sesleri {self.translations.get('mic_on', 'on') if self.system_on else self.translations.get('mic_off', 'off')}.")

    def toggle_microphone(self):
        if self.is_recording:
            QMessageBox.warning(self, self.translations.get("warning_title", "Uyarı"), self.translations.get("warning_recording_active", "Kayıt devam ederken mikrofonu kapatamazsınız."))
            return

        self.mic_on = not self.mic_on
        self._update_status_display()
        self.update_toggle_button_style(self.mic_button, "mic", self.mic_on)
        print(f"Mikrofon {self.translations.get('mic_on', 'on') if self.mic_on else self.translations.get('mic_off', 'off')}.")
    
    def update_toggle_button_style(self, button, name, is_on):
        """Açma/kapama butonlarının stilini durumuna göre günceller."""
        if is_on:
            style_sheet = f"""
                QPushButton#{button.objectName()} {{
                    border-image: url({resource_path('icons/' + name + '_basık.png')}) 0 0 0 0 stretch stretch;
                    border: none;
                }}
            """
        else:
            style_sheet = f"""
                QPushButton#{button.objectName()} {{
                    border-image: url({resource_path('icons/' + name + '_normal.png')}) 0 0 0 0 stretch stretch;
                    border: none;
                }}
                QPushButton#{button.objectName()}:hover {{
                    border-image: url({resource_path('icons/' + name + '_cursor.png')}) 0 0 0 0 stretch stretch;
                }}
            """
        button.setStyleSheet(style_sheet)
    
    def create_buttons(self, layout):
        self.rec_label = self.create_rec_label("rec", "rec_label")
        self.pause_label = self.create_rec_label("pause", "pause_label")
        self.stop_button = self.create_styled_button("stop", "stop_button")
        self.play_button = self.create_styled_button("play", "play_button")
        
        layout.addStretch()
        layout.addWidget(self.rec_label)
        layout.addWidget(self.pause_label)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.play_button)
        layout.addStretch()

        self.rec_label.installEventFilter(self)
        self.pause_label.installEventFilter(self)

        self.rec_label.mousePressEvent = self.start_recording
        self.pause_label.mousePressEvent = self.toggle_pause
        self.stop_button.clicked.connect(self.stop_recording)
    
    def eventFilter(self, obj, event):
        if obj == self.rec_label:
            if event.type() == QEvent.Enter:
                self.rec_label.setPixmap(QPixmap(resource_path("icons/rec_cursor.png")))
            elif event.type() == QEvent.Leave:
                if not self.is_recording:
                    self.rec_label.setPixmap(QPixmap(resource_path("icons/rec_normal.png")))
        
        elif obj == self.pause_label:
            if not self.is_paused:
                if event.type() == QEvent.Enter:
                    self.pause_label.setPixmap(QPixmap(resource_path("icons/pause_cursor.png")))
                elif event.type() == QEvent.Leave:
                    self.pause_label.setPixmap(QPixmap(resource_path("icons/pause_normal.png")))
        
        return super().eventFilter(obj, event)

    def create_styled_button(self, name, object_name):
        button = QPushButton()
        button.setObjectName(object_name)
        
        pixmap = QPixmap(resource_path(f"icons/{name}_normal.png"))
        if not pixmap.isNull():
            button.setFixedSize(pixmap.size())
        
        button.setStyleSheet(f"""
            QPushButton#{object_name} {{
                border-image: url({resource_path('icons/' + name + '_normal.png')}) 0 0 0 0 stretch stretch;
                border: none;
            }}
            QPushButton#{object_name}:hover {{
                border-image: url({resource_path('icons/' + name + '_cursor.png')}) 0 0 0 0 stretch stretch;
            }}
            QPushButton#{object_name}:pressed {{
                border-image: url({resource_path('icons/' + name + '_basık.png')}) 0 0 0 0 stretch stretch;
            }}
        """)
        return button
    
    def create_rec_label(self, name, object_name):
        label = QLabel()
        label.setObjectName(object_name)

        pixmap = QPixmap(resource_path(f"icons/{name}_normal.png"))
        if not pixmap.isNull():
            label.setFixedSize(pixmap.size())
            label.setPixmap(pixmap)
        
        return label

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet("""
            QMenuBar {
                background-color: #3C3C3C;
                color: white;
            }
            QMenuBar::item:selected {
                background-color: #5C5C5C;
            }
            QMenu {
                background-color: #3C3C3C;
                color: white;
                border: 1px solid #5C5C5C;
            }
            QMenu::item:selected {
                background-color: #5C5C5C;
            }
        """)
        
        file_menu = menu_bar.addMenu(self.translations.get("menu_file", "Dosya"))
        settings_menu = menu_bar.addMenu(self.translations.get("menu_settings", "Ayarlar"))
        
        open_action = QAction(self.translations.get("action_open", "Aç..."), self)
        save_as_action = QAction(self.translations.get("action_save_as", "Farklı Kaydet..."), self)
        exit_action = QAction(self.translations.get("action_exit", "Çıkış"), self)
        
        format_action = QAction(self.translations.get("action_record_format", "Kayıt Formatı..."), self)
        language_action = QAction(self.translations.get("action_language", "Dil..."), self)

        open_action.triggered.connect(self.open_file)
        save_as_action.triggered.connect(self.save_file_as)
        exit_action.triggered.connect(self.close)
        
        format_action.triggered.connect(self.show_format_options)
        language_action.triggered.connect(self.show_language_options)

        file_menu.addAction(open_action)
        file_menu.addAction(save_as_action)
        file_menu.addSeparator() 
        file_menu.addAction(exit_action)
        
        settings_menu.addAction(format_action)
        settings_menu.addAction(language_action)

        about_menu = menu_bar.addMenu(self.translations.get("menu_about", "Hakkında"))
        about_action = QAction(self.translations.get("menu_about", "Hakkında"), self)
        about_action.triggered.connect(self.show_about_dialog)
        about_menu.addAction(about_action)

    def show_language_options(self):
        # Kullanılabilir dilleri tara ve gösterilecek isimlerini al
        available_languages = {}
        if self.languages_dir:
            for filename in os.listdir(self.languages_dir):
                if filename.endswith('.json'):
                    lang_code = filename.replace('.json', '')
                    try:
                        with open(os.path.join(self.languages_dir, filename), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            display_name = data.get("language_name", lang_code.upper())
                            available_languages[display_name] = lang_code
                    except (IOError, json.JSONDecodeError):
                        continue

        lang_list = list(available_languages.keys())
        current_display_name = next((key for key, value in available_languages.items() if value == self.current_language), self.current_language.upper())
        current_index = lang_list.index(current_display_name) if current_display_name in lang_list else 0

        lang, ok = QInputDialog.getItem(self, 
                                        self.translations.get("action_language", "Dil"), 
                                        self.translations.get("info_select_language", "Lütfen bir dil seçin:"), 
                                        lang_list, 
                                        current_index, False)

        if ok and lang:
            new_lang_code = available_languages[lang]
            if new_lang_code != self.current_language:
                self.current_language = new_lang_code
                self.save_settings()
                QMessageBox.information(self, self.translations.get("info_title", "Bilgi"), self.translations.get("info_restart_required", "Dil ayarı değiştirildi. Değişikliklerin etkili olması için uygulama yeniden başlatılacak."))
                self.restart_app()

    def restart_app(self):
        """Uygulamayı yeniden başlatır."""
        QApplication.quit()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def show_format_options(self):
        options = [".WAV", ".MP3", ".FLAC", ".OGG", ".AAC"]
        current_format = self.record_format
        
        format_tuple = QInputDialog.getItem(self, self.translations.get("action_record_format", "Kayıt Formatı..."), self.translations.get("info_select_format", "Lütfen bir kayıt formatı seçin:"), options, options.index(current_format), False)
        
        if format_tuple[1]:
            new_format = format_tuple[0]
            if new_format != self.record_format:
                self.record_format = new_format
                self.save_settings()
                QMessageBox.information(self, self.translations.get("info_title", "Bilgi"), self.translations.get("info_format_set", "Kayıt formatı başarıyla {format} olarak ayarlandı.").format(format=self.record_format))
                self._update_status_display()

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.translations.get("action_open", "Aç..."), "", f"{self.translations.get('file_type_audio', 'Ses Dosyaları')} (*.wav)")
        if file_path:
            self.add_record_to_table(file_path)

    def save_file_as(self):
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, self.translations.get("warning_title", "Uyarı"), self.translations.get("warning_select_for_save", "Lütfen farklı kaydetmek istediğiniz kaydı listeden seçin."))
            return

        file_name = self.table_widget.item(selected_rows[0].row(), 0).text()
        # Kayıt uzantısını belirle
        file_extension = os.path.splitext(file_name)[1]
        
        source_path = os.path.join(self.record_path, file_name)
        
        if not os.path.exists(source_path):
            QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_file_not_found", "Kaynak dosyası bulunamadı: '{filename}'").format(filename=file_name))
            return

        destination_path, _ = QFileDialog.getSaveFileName(self, self.translations.get("action_save_as", "Farklı Kaydet..."), source_path, f"{file_extension.upper().replace('.', '')} {self.translations.get('file_type', 'Dosyaları')} (*{file_extension})")

        if destination_path:
            try:
                shutil.copyfile(source_path, destination_path)
                QMessageBox.information(self, self.translations.get("success_title", "Başarılı"), self.translations.get("success_file_saved", "Kayıt başarıyla kaydedildi:\n{path}").format(path=destination_path))
            except Exception as e:
                QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_save_file", "Dosya kaydedilirken bir hata oluştu: {error}").format(error=e))

    def _save_recording_to_path(self, full_path, format):
        try:
            temp_wav_path = os.path.splitext(full_path)[0] + ".wav"
            
            # İlk olarak WAV formatında kaydet
            wf = wave.open(temp_wav_path, 'wb')
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.p.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE)
            wf.writeframes(b''.join(self.frames))
            wf.close()

            if format.lower() == ".wav":
                os.rename(temp_wav_path, full_path)
                print(f"Kayıt durduruldu ve {full_path} dosyasına kaydedildi.")
            else:
                # pydub ile diğer formatlara dönüştür
                audio_segment = AudioSegment.from_wav(temp_wav_path)
                audio_segment.export(full_path, format=format.replace(".", ""))
                os.remove(temp_wav_path)
                print(f"Kayıt durduruldu, {format.upper()} formatına dönüştürüldü ve {full_path} dosyasına kaydedildi.")
        
        except Exception as e:
            QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_save_file", "Dosya kaydedilirken bir hata oluştu: {error}").format(error=e))

    def show_about_dialog(self):
        msgBox = QMessageBox()
        msgBox.setWindowTitle(self.translations.get("about_title", "Hakkında - Echo Ses Kaydedici"))
        msgBox.setStyleSheet("QMessageBox { background-color: #363636; }"
                             "QLabel { color: white; }")
        
        about_text = f"""
                          <p style="color:white;">{self.translations.get('about_text_1', "Echo Ses Kaydedici")}</p>
                          <hr>
                          <p style="color:white;">{self.translations.get('about_text_2', "Sürüm: 1.0.1")}</p>
                          <p style="color:white;">{self.translations.get('about_text_3', "Lisans: GNU GPLv3")}</p>
                          <p style="color:white;">{self.translations.get('about_text_4', "Geliştirici: Aydın Serhat KILIÇOĞLU")}</p>
                          <p style="color:white;">{self.translations.get('about_text_5', "Programlama Dili: Python3")}</p>
                          <p style="color:white;">{self.translations.get('about_text_6', "Arayüz: Qt")}</p>
                          <hr>
                          <p style="color:white;">{self.translations.get('about_text_7', "Echo Ses Kaydedici, kullanımı kolay ve hafif bir ses kaydedicisidir.")}</p>
                          <p style="color:white;">{self.translations.get('about_text_8', "Bu program hiçbir garanti getirmez.")}</p>
                          """

        msgBox.about(self, self.translations.get("about_title", "Hakkında"), about_text)

    def setup_table(self):
        self.table_widget.setColumnCount(4)
        self.table_widget.setHorizontalHeaderLabels([
            self.translations.get("table_header_recordings", "Kayıtlar"),
            self.translations.get("table_header_duration", "Süre"),
            self.translations.get("table_header_size", "Boyut"),
            self.translations.get("table_header_format", "Biçem")
        ])
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table_widget.setStyleSheet("""
            QTableWidget {
                background-color: #2D2D2D;
                alternate-background-color: #3C3C3C;
                color: white;
            }
            QHeaderView::section {
                background-color: #4C4C4C;
                color: white;
            }
        """)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setShowGrid(False)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    
    def add_record_to_table(self, file_path):
        try:
            row_position = self.table_widget.rowCount()
            self.table_widget.insertRow(row_position)
            
            file_info = QFileInfo(file_path)
            file_name = file_info.fileName()
            file_extension = os.path.splitext(file_name)[1].upper()
            file_size_kb = round(file_info.size() / 1024, 2)

            duration_text = "N/A" # Farklı formatlarda süre hesaplamak daha karmaşıktır.
            try:
                if file_extension == ".WAV":
                    with wave.open(file_path, 'rb') as wf:
                        frames = wf.getnframes()
                        rate = wf.getframerate()
                        duration_seconds = frames / float(rate)
                        duration_minutes = int(duration_seconds // 60)
                        duration_seconds_rem = int(duration_seconds % 60)
                        duration_text = f"{duration_minutes:02}:{duration_seconds_rem:02}"
                else:
                    audio_segment = AudioSegment.from_file(file_path)
                    duration_seconds = len(audio_segment) / 1000.0
                    duration_minutes = int(duration_seconds // 60)
                    duration_seconds_rem = int(duration_seconds % 60)
                    duration_text = f"{duration_minutes:02}:{duration_seconds_rem:02}"
            except Exception as e:
                print(f"Süre hesaplanırken hata oluştu: {e}")

            self.table_widget.setItem(row_position, 0, QTableWidgetItem(file_name))
            self.table_widget.setItem(row_position, 1, QTableWidgetItem(duration_text))
            self.table_widget.setItem(row_position, 2, QTableWidgetItem(f"{file_size_kb} KB"))
            self.table_widget.setItem(row_position, 3, QTableWidgetItem(file_extension))
            
        except Exception as e:
            QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_table_add", "Tabloya kayıt eklenirken bir hata oluştu: {error}").format(error=e))
        
    def start_recording(self, event):
        if self.is_recording:
            return
        
        if not self.mic_on:
            QMessageBox.information(self, self.translations.get("warning_title", "Uyarı"), self.translations.get("warning_mic_off", "Mikrofon kapalı. Lütfen kayda başlamadan önce mikrofonu açın."))
            return

        self.is_recording = True
        self.is_paused = False
        self.frames = []
        self.start_time = time.time()
        self._update_status_display(current_status="status_recording")
        
        self.update_toggle_button_style(self.mic_button, "mic", True)

        try:
            print("Mevcut Ses Aygıtları:")
            info = self.p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            for i in range(numdevices):
                dev_info = self.p.get_device_info_by_host_api_device_index(0, i)
                print(f"  [{i}] {dev_info.get('name')} (Giriş: {dev_info.get('maxInputChannels')}, Çıkış: {dev_info.get('maxOutputChannels')})")
        except Exception as e:
            print(f"Ses aygıtları listelenirken hata oluştu: {e}")
            
        try:
            self.stream = self.p.open(format=self.FORMAT,
                                      channels=self.CHANNELS,
                                      rate=self.RATE,
                                      input=True,
                                      frames_per_buffer=self.CHUNK,
                                      stream_callback=self.callback)
            print("Kayıt başlatıldı.")
        except Exception as e:
            QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_record_start", "Kayıt başlatılamadı: {error}\n\nLütfen mikrofonunuzu kontrol edin ve bu uygulamanın ses aygıtına erişim izni olduğundan emin olun.").format(error=e))
            self.is_recording = False
            self.mic_on = False
            self._update_status_display(current_status="status_error")

        pixmap = QPixmap(resource_path("icons/rec_basık.png"))
        if not pixmap.isNull():
            self.rec_label.setPixmap(pixmap)
            
    def callback(self, in_data, frame_count, time_info, status):
        if self.is_recording and not self.is_paused:
            self.frames.append(in_data)
            return (in_data, pyaudio.paContinue)
        else:
            return (None, pyaudio.paContinue)

    def stop_recording(self):
        if not self.is_recording and (not self.playback_thread or not self.playback_thread.isRunning()):
            return

        if self.is_recording:
            self.is_recording = False
            self.stream.stop_stream()
            self.stream.close()
            
            if not self.frames:
                QMessageBox.warning(self, self.translations.get("warning_title", "Uyarı"), self.translations.get("warning_no_audio_data", "Hiçbir ses verisi kaydedilmedi. Dosya oluşturulmadı."))
                print("Kayıt verisi bulunamadı. Dosya oluşturulmadı.")
            else:
                counter = 1
                file_extension = self.record_format
                file_name_base = "rec"
                file_name = f"{file_name_base}{counter}{file_extension}"
                full_path = os.path.join(self.record_path, file_name)
                
                while os.path.exists(full_path):
                    counter += 1
                    file_name = f"{file_name_base}{counter}{file_extension}"
                    full_path = os.path.join(self.record_path, file_name)

                self._save_recording_to_path(full_path, file_extension)
                self.add_record_to_table(full_path)
        
        if self.playback_thread and self.playback_thread.isRunning():
            self.playback_thread.is_playing = False
            self.playback_thread.quit()
            self.playback_thread.wait()
            self.on_playback_finished(None)

        self._update_status_display(current_status="status_ready")
        
        pixmap = QPixmap(resource_path("icons/rec_normal.png"))
        if not pixmap.isNull():
            self.rec_label.setPixmap(pixmap)
        
        pixmap = QPixmap(resource_path("icons/pause_normal.png"))
        if not pixmap.isNull():
            self.pause_label.setPixmap(pixmap)
            self.is_paused = False
        
    def play_recording(self):
        selected_row = self.table_widget.currentRow()
        if selected_row == -1:
            QMessageBox.information(self, self.translations.get("warning_title", "Uyarı"), self.translations.get("warning_select_recording", "Lütfen önce listeden bir kayıt seçin."))
            return

        file_name = self.table_widget.item(selected_row, 0).text()
        full_path = os.path.join(self.record_path, file_name)
        
        if self.playback_thread and self.playback_thread.isRunning():
            QMessageBox.warning(self, self.translations.get("warning_title", "Uyarı"), self.translations.get("warning_playback_active", "Şu anda bir kayıt oynatılıyor."))
            return

        try:
            if not os.path.exists(full_path):
                QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_file_not_found", "Kaynak dosyası bulunamadı: '{filename}'").format(filename=file_name))
                return
            
            # Farklı formatlarda oynatmayı sağlamak için pydub ile WAV'a dönüştür
            audio_segment = AudioSegment.from_file(full_path)
            temp_wav_path = os.path.splitext(full_path)[0] + "_temp.wav"
            audio_segment.export(temp_wav_path, format="wav")

            self._update_status_display(current_status="status_playing")
            self.play_button.setDisabled(True)
            self.play_button.setStyleSheet(f"""
                QPushButton#play_button {{
                    border-image: url({resource_path('icons/play_basık.png')}) 0 0 0 0 stretch stretch;
                    border: none;
                }}
            """)
            
            self.playback_thread = PlaybackThread({'path': temp_wav_path})
            self.playback_thread.finished.connect(lambda: self.on_playback_finished(temp_wav_path))
            self.playback_thread.error.connect(lambda msg: self.on_playback_error(msg, temp_wav_path))
            self.playback_thread.start()

        except Exception as e:
            QMessageBox.critical(self, self.translations.get("error_title", "Hata"), self.translations.get("error_playback_start", "Oynatma başlatma sırasında bir hata oluştu: {error}").format(error=e))
            self.on_playback_error(f"Oynatma başlatma sırasında bir hata oluştu: {e}", temp_wav_path if 'temp_wav_path' in locals() else None)

    def on_playback_finished(self, temp_wav_path):
        self._update_status_display(current_status="status_ready")
        self.play_button.setDisabled(False)
        self.play_button.setStyleSheet(f"""
            QPushButton#play_button {{
                border-image: url({resource_path('icons/play_normal.png')}) 0 0 0 0 stretch stretch;
            }}
            QPushButton#play_button:hover {{
                border-image: url({resource_path('icons/play_cursor.png')}) 0 0 0 0 stretch stretch;
            }}
            QPushButton#play_button:pressed {{
                border-image: url({resource_path('icons/play_basık.png')}) 0 0 0 0 stretch stretch;
            }}
        """)
        if temp_wav_path and os.path.exists(temp_wav_path):
            os.remove(temp_wav_path)
        print("Kayıt oynatma tamamlandı.")

    def on_playback_error(self, message, temp_wav_path):
        QMessageBox.critical(self, self.translations.get("playback_error_dialog_title", "Oynatma Hatası"), message)
        self._update_status_display(current_status="status_playback_error")
        self.play_button.setDisabled(False)
        self.play_button.setStyleSheet(f"""
            QPushButton#play_button {{
                border-image: url({resource_path('icons/play_normal.png')}) 0 0 0 0 stretch stretch;
            }}
            QPushButton#play_button:hover {{
                border-image: url({resource_path('icons/play_cursor.png')}) 0 0 0 0 stretch stretch;
            }}
            QPushButton#play_button:pressed {{
                border-image: url({resource_path('icons/play_basık.png')}) 0 0 0 0 stretch stretch;
            }}
        """)
        if temp_wav_path and os.path.exists(temp_wav_path):
            os.remove(temp_wav_path)

    def toggle_pause(self, event):
        if not self.is_recording:
            print("Kayıt aktif değil. Pause butonu kullanılamaz.")
            return

        self.is_paused = not self.is_paused
        
        if self.is_paused:
            self._update_status_display(current_status="status_paused")
            pause_movie = QMovie(resource_path("icons/pause_basık_animated.gif"))
            if pause_movie.isValid():
                self.pause_label.setMovie(pause_movie)
                pause_movie.start()
        else:
            self._update_status_display(current_status="status_recording")
            pixmap = QPixmap(resource_path("icons/pause_normal.png"))
            if not pixmap.isNull():
                self.pause_label.setPixmap(pixmap)
            
if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = SoundRecorderApp()
    ex.show()
    sys.exit(app.exec_())
