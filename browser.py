"""fire_engine: a small private-by-default browser built with PyQt6 WebEngine.

This is intentionally a browser shell, not a new rendering engine. Qt WebEngine
provides the Chromium renderer and network stack; this file provides private
profiles, tabs, navigation, permissions, downloads, fullscreen, and diagnostics.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QToolBar,
)
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView


APP_NAME = "fire_engine"
HOME_URL = QUrl("https://www.youtube.com/")
SEARCH_URL = "https://duckduckgo.com/?q={}"


def resolve_address(text: str) -> QUrl:
    """Turn address-bar input into a URL or a privacy-oriented web search."""
    value = text.strip()
    if not value:
        return HOME_URL

    lower = value.lower()
    known_scheme = lower.startswith(
        ("http://", "https://", "file://", "about:", "data:")
    )
    looks_like_search = " " in value or (
        "." not in value and not value.startswith("localhost")
    )

    if known_scheme:
        return QUrl.fromUserInput(value)
    if looks_like_search:
        return QUrl(SEARCH_URL.format(quote_plus(value)))
    if value.startswith(("localhost", "127.0.0.1", "[::1]")):
        return QUrl.fromUserInput(value)
    return QUrl(f"https://{value}")


class BrowserView(QWebEngineView):
    """A web view that sends popup/new-window requests to a new browser tab."""

    def __init__(
        self,
        browser: "FireEngineBrowser",
        profile: QWebEngineProfile,
    ) -> None:
        super().__init__(browser)
        self.browser = browser
        self.setPage(QWebEnginePage(profile, self))

    def createWindow(  # noqa: N802 - Qt's virtual method name
        self,
        window_type: QWebEnginePage.WebWindowType,
    ) -> QWebEngineView:
        del window_type
        return self.browser.add_tab(QUrl("about:blank"), switch=True)


class FireEngineBrowser(QMainWindow):
    """Private-by-default, tabbed browser window."""

    def __init__(self, initial_url: QUrl | None = None) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"{APP_NAME} — Private")
        self.resize(1360, 880)
        self._active_downloads: dict[int, QWebEngineDownloadRequest] = {}
        self._is_page_fullscreen = False

        self.profile = self._create_private_profile()
        self.profile.downloadRequested.connect(self._download_requested)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self._current_tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBarDoubleClicked.connect(self._tab_bar_double_clicked)
        self.setCentralWidget(self.tabs)

        self.toolbar = QToolBar("Navigation")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.addToolBar(self.toolbar)
        self._build_navigation_bar()
        self._build_menus()

        self.statusBar().showMessage("Private session: history and cookies stay in memory")
        self.add_tab(initial_url or HOME_URL, switch=True)

    def _create_private_profile(self) -> QWebEngineProfile:
        # A profile created without a storage name is explicitly off-the-record.
        # The application owns the profile so it outlives every page. The window
        # deletes its views first on close, avoiding Qt's profile/page teardown race.
        profile = QWebEngineProfile(QApplication.instance())
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        profile.setHttpAcceptLanguage("en-US,en;q=0.9")

        permission_policy = getattr(
            QWebEngineProfile,
            "PersistentPermissionsPolicy",
            None,
        )
        if permission_policy is not None and hasattr(
            profile,
            "setPersistentPermissionsPolicy",
        ):
            profile.setPersistentPermissionsPolicy(permission_policy.StoreInMemory)

        settings = profile.settings()
        self._set_web_attribute(settings, "JavascriptEnabled", True)
        self._set_web_attribute(settings, "JavascriptCanOpenWindows", True)
        self._set_web_attribute(settings, "LocalStorageEnabled", True)
        self._set_web_attribute(settings, "FullScreenSupportEnabled", True)
        self._set_web_attribute(settings, "PlaybackRequiresUserGesture", False)
        self._set_web_attribute(settings, "WebGLEnabled", True)
        self._set_web_attribute(settings, "Accelerated2dCanvasEnabled", True)
        self._set_web_attribute(settings, "PdfViewerEnabled", True)
        self._set_web_attribute(settings, "ErrorPageEnabled", True)
        self._set_web_attribute(settings, "ScreenCaptureEnabled", True)

        # Privacy/security defaults. TLS errors are deliberately not bypassed.
        self._set_web_attribute(settings, "HyperlinkAuditingEnabled", False)
        self._set_web_attribute(settings, "PluginsEnabled", False)
        self._set_web_attribute(settings, "LocalContentCanAccessRemoteUrls", False)
        self._set_web_attribute(settings, "LocalContentCanAccessFileUrls", False)
        return profile

    @staticmethod
    def _set_web_attribute(
        settings: QWebEngineSettings,
        name: str,
        enabled: bool,
    ) -> None:
        attribute = getattr(QWebEngineSettings.WebAttribute, name, None)
        if attribute is not None:
            settings.setAttribute(attribute, enabled)

    def _build_navigation_bar(self) -> None:
        self.back_action = self._add_toolbar_action(
            "Back",
            "Alt+Left",
            self.go_back,
        )
        self.forward_action = self._add_toolbar_action(
            "Forward",
            "Alt+Right",
            self.go_forward,
        )
        self.reload_action = self._add_toolbar_action(
            "Reload",
            QKeySequence.StandardKey.Refresh,
            self.reload_page,
        )
        self._add_toolbar_action("Stop", "Esc", self.stop_loading)
        self._add_toolbar_action("Home", "Alt+Home", self.go_home)

        self.url_bar = QLineEdit()
        self.url_bar.setClearButtonEnabled(True)
        self.url_bar.setPlaceholderText("Search privately or enter an address")
        self.url_bar.setMinimumWidth(500)
        self.url_bar.returnPressed.connect(self.navigate_to_address)
        self.toolbar.addWidget(self.url_bar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumWidth(110)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.toolbar.addWidget(self.progress)

        private_label = QLabel("  Private  ")
        private_label.setToolTip(
            "Off-the-record profile: cookies, cache, permissions, and history are memory-only"
        )
        self.toolbar.addWidget(private_label)
        self._add_toolbar_action("+", QKeySequence.StandardKey.AddTab, self.new_tab)

    def _add_toolbar_action(
        self,
        text: str,
        shortcut: str | QKeySequence.StandardKey,
        callback,
    ) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        self.toolbar.addAction(action)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self._menu_action("New Tab", "Ctrl+T", self.new_tab))
        file_menu.addAction(
            self._menu_action("Close Tab", "Ctrl+W", self.close_current_tab)
        )
        file_menu.addSeparator()
        file_menu.addAction(
            self._menu_action("Open Location", "Ctrl+L", self.focus_address_bar)
        )
        file_menu.addAction(self._menu_action("Quit", "Ctrl+Q", self.close))

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self._menu_action("Zoom In", "Ctrl++", self.zoom_in))
        view_menu.addAction(self._menu_action("Zoom Out", "Ctrl+-", self.zoom_out))
        view_menu.addAction(
            self._menu_action("Actual Size", "Ctrl+0", self.reset_zoom)
        )
        view_menu.addAction(
            self._menu_action("Fullscreen", "F11", self.toggle_fullscreen)
        )

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(
            self._menu_action(
                "Media Diagnostics",
                "Ctrl+Shift+M",
                self.show_media_diagnostics,
            )
        )
        tools_menu.addAction(
            self._menu_action("Clear Session Data", "", self.clear_session_data)
        )

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(self._menu_action(f"About {APP_NAME}", "", self.show_about))

    def _menu_action(self, text: str, shortcut: str, callback) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        return action

    def current_view(self) -> BrowserView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, BrowserView) else None

    def add_tab(self, url: QUrl | None = None, switch: bool = True) -> BrowserView:
        view = BrowserView(self, self.profile)
        index = self.tabs.addTab(view, "New tab")

        view.urlChanged.connect(lambda new_url, v=view: self._url_changed(v, new_url))
        view.titleChanged.connect(lambda title, v=view: self._title_changed(v, title))
        view.iconChanged.connect(lambda icon, v=view: self._icon_changed(v, icon))
        view.loadStarted.connect(lambda v=view: self._load_started(v))
        view.loadProgress.connect(lambda value, v=view: self._load_progress(v, value))
        view.loadFinished.connect(lambda ok, v=view: self._load_finished(v, ok))
        view.renderProcessTerminated.connect(
            lambda status, code, v=view: self._renderer_terminated(v, status, code)
        )
        view.page().featurePermissionRequested.connect(
            lambda origin, feature, page=view.page(): self._permission_requested(
                page,
                origin,
                feature,
            )
        )
        view.page().fullScreenRequested.connect(self._fullscreen_requested)

        if switch:
            self.tabs.setCurrentIndex(index)
        view.setUrl(url or HOME_URL)
        return view

    def new_tab(self) -> None:
        self.add_tab(HOME_URL, switch=True)

    def _tab_bar_double_clicked(self, index: int) -> None:
        if index == -1:
            self.new_tab()

    def close_current_tab(self) -> None:
        self.close_tab(self.tabs.currentIndex())

    def close_tab(self, index: int) -> None:
        if index < 0:
            return
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        widget.deleteLater()
        if self.tabs.count() == 0:
            self.close()

    def _current_tab_changed(self, index: int) -> None:
        del index
        view = self.current_view()
        if view is None:
            return
        self.url_bar.setText(view.url().toDisplayString())
        self._set_window_title(view.title())
        self._update_navigation_state(view)

    def navigate_to_address(self) -> None:
        view = self.current_view()
        if view is not None:
            view.setUrl(resolve_address(self.url_bar.text()))

    def focus_address_bar(self) -> None:
        self.url_bar.setFocus()
        self.url_bar.selectAll()

    def go_back(self) -> None:
        view = self.current_view()
        if view is not None:
            view.back()

    def go_forward(self) -> None:
        view = self.current_view()
        if view is not None:
            view.forward()

    def reload_page(self) -> None:
        view = self.current_view()
        if view is not None:
            view.reload()

    def stop_loading(self) -> None:
        view = self.current_view()
        if view is not None:
            view.stop()

    def go_home(self) -> None:
        view = self.current_view()
        if view is not None:
            view.setUrl(HOME_URL)

    def _url_changed(self, view: BrowserView, url: QUrl) -> None:
        if view is self.current_view():
            self.url_bar.setText(url.toDisplayString())
            self.url_bar.setCursorPosition(0)
            self._update_navigation_state(view)

    def _title_changed(self, view: BrowserView, title: str) -> None:
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabText(index, title.strip() or "New tab")
            self.tabs.setTabToolTip(index, title.strip() or view.url().toString())
        if view is self.current_view():
            self._set_window_title(title)

    def _icon_changed(self, view: BrowserView, icon) -> None:
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabIcon(index, icon)

    def _set_window_title(self, page_title: str) -> None:
        title = page_title.strip() if page_title else "New tab"
        self.setWindowTitle(f"{title} — {APP_NAME} Private")

    def _load_started(self, view: BrowserView) -> None:
        if view is self.current_view():
            self.progress.setValue(0)
            self.progress.show()
            self.statusBar().showMessage("Loading…")

    def _load_progress(self, view: BrowserView, value: int) -> None:
        if view is self.current_view():
            self.progress.setValue(value)

    def _load_finished(self, view: BrowserView, ok: bool) -> None:
        if view is self.current_view():
            self.progress.hide()
            self._update_navigation_state(view)
            self.statusBar().showMessage(
                "Ready" if ok else "Page failed to load — check the address or network",
                5000,
            )

    def _update_navigation_state(self, view: BrowserView) -> None:
        self.back_action.setEnabled(view.history().canGoBack())
        self.forward_action.setEnabled(view.history().canGoForward())

    def _renderer_terminated(self, view: BrowserView, status, exit_code: int) -> None:
        if view is self.current_view():
            self.progress.hide()
        QMessageBox.warning(
            self,
            "Page renderer stopped",
            f"The page process stopped ({status.name}, exit code {exit_code}).\n"
            "Reload the tab. Repeated crashes usually indicate a GPU/driver issue.",
        )

    def _permission_requested(
        self,
        page: QWebEnginePage,
        origin: QUrl,
        feature: QWebEnginePage.Feature,
    ) -> None:
        readable = {
            "Geolocation": "location",
            "MediaAudioCapture": "microphone",
            "MediaVideoCapture": "camera",
            "MediaAudioVideoCapture": "camera and microphone",
            "DesktopVideoCapture": "screen sharing",
            "DesktopAudioVideoCapture": "screen and system audio sharing",
            "MouseLock": "mouse lock",
            "Notifications": "notifications",
        }.get(feature.name, feature.name)

        answer = QMessageBox.question(
            self,
            "Private permission request",
            f"Allow {origin.host() or origin.toString()} to use {readable}?\n\n"
            "The decision lasts only for this private session.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        policy = (
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if answer == QMessageBox.StandardButton.Yes
            else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        )
        page.setFeaturePermission(origin, feature, policy)

    def _fullscreen_requested(self, request) -> None:
        request.accept()
        self._is_page_fullscreen = request.toggleOn()
        if self._is_page_fullscreen:
            self.menuBar().hide()
            self.toolbar.hide()
            self.tabs.tabBar().hide()
            self.showFullScreen()
        else:
            self.showNormal()
            self.menuBar().show()
            self.toolbar.show()
            self.tabs.tabBar().show()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self.toolbar.show()
            self.tabs.tabBar().show()
        else:
            self.showFullScreen()

    def zoom_in(self) -> None:
        view = self.current_view()
        if view is not None:
            view.setZoomFactor(min(5.0, view.zoomFactor() + 0.1))

    def zoom_out(self) -> None:
        view = self.current_view()
        if view is not None:
            view.setZoomFactor(max(0.25, view.zoomFactor() - 0.1))

    def reset_zoom(self) -> None:
        view = self.current_view()
        if view is not None:
            view.setZoomFactor(1.0)

    def _download_requested(self, download: QWebEngineDownloadRequest) -> None:
        suggested = download.suggestedFileName() or "download"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save download (this file will remain after private mode closes)",
            suggested,
        )
        if not target:
            download.cancel()
            return

        path = Path(target).expanduser()
        download.setDownloadDirectory(str(path.parent))
        download.setDownloadFileName(path.name)
        self._active_downloads[download.id()] = download
        download.receivedBytesChanged.connect(
            lambda item=download: self._download_progress(item)
        )
        download.isFinishedChanged.connect(
            lambda item=download: self._download_finished(item)
        )
        download.accept()
        self.statusBar().showMessage(f"Downloading {path.name}…")

    def _download_progress(self, download: QWebEngineDownloadRequest) -> None:
        total = download.totalBytes()
        received = download.receivedBytes()
        if total > 0:
            percent = int(received * 100 / total)
            self.statusBar().showMessage(
                f"Downloading {download.downloadFileName()}: {percent}%"
            )

    def _download_finished(self, download: QWebEngineDownloadRequest) -> None:
        if not download.isFinished():
            return
        state = download.state()
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            message = f"Downloaded {download.downloadFileName()}"
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            message = f"Download failed: {download.interruptReasonString()}"
        else:
            message = "Download cancelled"
        self.statusBar().showMessage(message, 8000)
        self._active_downloads.pop(download.id(), None)

    def show_media_diagnostics(self) -> None:
        view = self.current_view()
        if view is None:
            return

        script = """
            (() => {
                const video = document.createElement('video');
                return {
                    webmVp9: video.canPlayType('video/webm; codecs="vp9, opus"'),
                    webmAv1: video.canPlayType('video/webm; codecs="av01.0.05M.08, opus"'),
                    mp4H264: video.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'),
                    mediaSource: typeof MediaSource !== 'undefined',
                    encryptedMedia: typeof navigator.requestMediaKeySystemAccess === 'function',
                    userAgent: navigator.userAgent
                };
            })();
        """
        view.page().runJavaScript(script, self._show_media_result)

    def _show_media_result(self, result) -> None:
        if not isinstance(result, dict):
            QMessageBox.warning(self, "Media diagnostics", "Diagnostics did not run.")
            return

        def support(value) -> str:
            return value if value in {"probably", "maybe"} else "not available"

        h264 = support(result.get("mp4H264", ""))
        note = ""
        if h264 == "not available":
            note = (
                "\n\nH.264/AAC is not present in this Qt WebEngine build. Python "
                "settings cannot add a codec. YouTube should prefer VP9/AV1 where "
                "available; H.264-only videos require Qt WebEngine built with "
                "-webengine-proprietary-codecs and the appropriate codec licences."
            )

        QMessageBox.information(
            self,
            "Media diagnostics",
            "Qt WebEngine media support:\n"
            f"• WebM VP9/Opus: {support(result.get('webmVp9', ''))}\n"
            f"• WebM AV1/Opus: {support(result.get('webmAv1', ''))}\n"
            f"• MP4 H.264/AAC: {h264}\n"
            f"• Media Source Extensions: {bool(result.get('mediaSource'))}\n"
            f"• Encrypted Media API: {bool(result.get('encryptedMedia'))}\n\n"
            f"User agent:\n{result.get('userAgent', 'unknown')}"
            f"{note}",
        )

    def clear_session_data(self) -> None:
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearAllVisitedLinks()
        self.profile.clearHttpCache()
        self.statusBar().showMessage("In-memory cookies, cache, and visited links cleared", 5000)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"{APP_NAME} is a private browser shell powered by Qt WebEngine.\n\n"
            "Private mode keeps browser-managed cookies, cache, permissions, and "
            "history in memory. It does not hide traffic from websites, your network "
            "provider, or your employer, and files you download remain on disk.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        for download in tuple(self._active_downloads.values()):
            if not download.isFinished():
                download.cancel()
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearAllVisitedLinks()
        self.profile.clearHttpCache()
        super().closeEvent(event)


def main() -> int:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_NAME)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    initial_url = resolve_address(sys.argv[1]) if len(sys.argv) > 1 else HOME_URL
    browser = FireEngineBrowser(initial_url)
    browser.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
