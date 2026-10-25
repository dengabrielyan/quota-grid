import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    property var appletContext: root
    property var snapshot: ({})
    property bool refreshing: false
    property bool statusBusy: false
    property bool autoRefreshAttempted: false
    property string commandError: ""
    property string activeStatusCommand: ""
    property string activeRefreshCommand: ""
    property double nowMs: Date.now()

    readonly property var providers: snapshot && Array.isArray(snapshot.providers)
        ? snapshot.providers
        : []
    readonly property int refreshIntervalSec: {
        var value = Number(snapshot && snapshot.interval_seconds);
        return isFinite(value) && value >= 60 ? value : 300;
    }
    readonly property string cli: "\"$HOME/.local/bin/quota-manager\""
    readonly property string statusCommand: cli + " status --json"
    readonly property string refreshCommand: cli + " refresh --json"
    readonly property string settingsCommand: cli + " settings"
    readonly property bool stale: {
        if (!snapshot || !snapshot.generated_at) {
            return false;
        }
        return (nowMs / 1000 - Number(snapshot.generated_at)) > Math.max(refreshIntervalSec * 3, 900);
    }
    readonly property string syncLabel: {
        if (refreshing) {
            return "SYNC";
        }
        if (!snapshot || !snapshot.generated_at) {
            return commandError.length > 0 ? "OFFLINE" : "IDLE";
        }
        if (stale) {
            return "STALE";
        }
        for (var i = 0; i < providers.length; i++) {
            if (providers[i].status !== "ok") {
                return "DEGRADED";
            }
        }
        return "LIVE";
    }
    readonly property color syncColor: {
        if (syncLabel === "LIVE") return "#79F7E4";
        if (syncLabel === "SYNC") return "#8BD9FF";
        if (syncLabel === "DEGRADED" || syncLabel === "STALE") return "#FFC15E";
        if (syncLabel === "OFFLINE") return "#FF6D83";
        return "#607780";
    }
    readonly property string lastUpdatedLabel: {
        if (!snapshot || !snapshot.generated_at) {
            return "ожидание данных";
        }
        var date = new Date(Number(snapshot.generated_at) * 1000);
        return "обновлено " + root.pad2(date.getHours()) + ":" + root.pad2(date.getMinutes());
    }
    readonly property string providerCountLabel: {
        return providers.length + " " + root.sourceWord(providers.length);
    }
    readonly property string tooltipBody: {
        if (providers.length === 0) {
            return commandError.length > 0 ? commandError : "Нет активных AI-сессий";
        }
        var lines = [];
        for (var i = 0; i < providers.length; i++) {
            var provider = providers[i];
            var parts = [];
            var windows = provider.windows || [];
            for (var j = 0; j < windows.length; j++) {
                var window = windows[j];
                parts.push(window.period_tag + " " + Math.round(Number(window.remaining_percent) || 0) + "%");
            }
            var suffix = provider.status === "ok"
                ? (parts.length > 0 ? parts.join("  ·  ") : "нет данных")
                : (provider.error || "ошибка");
            lines.push(provider.name + ": " + suffix);
        }
        return lines.join("\n");
    }

    toolTipMainText: "Quota Grid · остаток"
    toolTipSubText: root.tooltipBody
    Plasmoid.icon: "quota-grid"
    Plasmoid.title: "Quota Grid"
    Plasmoid.status: providers.length > 0 ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus

    compactRepresentation: CompactView {
        root: appletContext
        onActivated: appletContext.expanded = !appletContext.expanded
    }

    fullRepresentation: FullView {
        root: appletContext
    }

    function pad2(value) {
        return value < 10 ? "0" + value : "" + value;
    }

    function sourceWord(count) {
        var mod10 = count % 10;
        var mod100 = count % 100;
        if (mod10 === 1 && mod100 !== 11) {
            return "источник";
        }
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
            return "источника";
        }
        return "источников";
    }

    function accentFor(providerId) {
        if (providerId === "claude") return "#FFA17D";
        if (providerId === "codex") return "#6CF5D5";
        if (providerId === "zcode") return "#A895FF";
        return "#93B7C2";
    }

    function quotaColor(value, accent) {
        var number = Number(value);
        if (!isFinite(number)) {
            return accent;
        }
        if (number <= 0.5) {
            return "#FF6078";
        }
        if (number <= 15) {
            return "#FFC15E";
        }
        return accent;
    }

    function stateColor(label) {
        if (label === "LIVE") return "#79F7E4";
        if (label === "LOW") return "#FFC15E";
        if (label === "LIMIT" || label === "AUTH" || label === "ERROR") return "#FF6D83";
        if (label === "PAUSED" || label === "EMPTY") return "#91A8B1";
        return "#91A8B1";
    }

    function minimumRemaining(provider) {
        if (!provider || !provider.windows || provider.windows.length === 0) {
            return null;
        }
        var bestByGroup = {};
        for (var i = 0; i < provider.windows.length; i++) {
            var window = provider.windows[i];
            var value = Number(window.remaining_percent);
            if (!isFinite(value)) {
                continue;
            }
            var key = String(window.title || window.id);
            if (!(key in bestByGroup) || value > bestByGroup[key]) {
                bestByGroup[key] = value;
            }
        }
        var minimum = null;
        for (var name in bestByGroup) {
            if (minimum === null || bestByGroup[name] < minimum) {
                minimum = bestByGroup[name];
            }
        }
        return minimum;
    }

    function providerStateLabel(provider) {
        if (!provider) {
            return "ERROR";
        }
        if (provider.status !== "ok") {
            var error = String(provider.error || "").toLowerCase();
            if (error.indexOf("auth") >= 0
                || error.indexOf("сесси") >= 0
                || error.indexOf("oauth") >= 0
                || error.indexOf("войдите") >= 0) {
                return "AUTH";
            }
            if (error.indexOf("времен") >= 0 || error.indexOf("огранич") >= 0) {
                return "PAUSED";
            }
            return "ERROR";
        }
        var minimum = minimumRemaining(provider);
        if (minimum === null) {
            return "EMPTY";
        }
        if (minimum <= 0.5) {
            return "LIMIT";
        }
        if (minimum <= 15) {
            return "LOW";
        }
        return "LIVE";
    }

    function formatDuration(seconds) {
        var value = Math.max(0, Math.round(Number(seconds) || 0));
        var days = Math.floor(value / 86400);
        var hours = Math.floor((value % 86400) / 3600);
        var minutes = Math.floor((value % 3600) / 60);
        if (days > 0) {
            return days + " д " + hours + " ч";
        }
        if (hours > 0) {
            return hours + " ч " + minutes + " мин";
        }
        return Math.max(1, minutes) + " мин";
    }

    function resetLabel(timestamp) {
        var value = Number(timestamp);
        if (!isFinite(value) || value <= 0) {
            return "без сброса";
        }
        var seconds = value - (nowMs / 1000);
        if (seconds <= 0) {
            return "обновляется";
        }
        if (seconds > 604800) {
            var months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
            var date = new Date(value * 1000);
            return "сброс " + date.getDate() + " " + months[date.getMonth()];
        }
        return "сброс через " + formatDuration(seconds);
    }

    function formatTokens(value) {
        var number = Number(value);
        if (!isFinite(number)) {
            return "—";
        }
        if (number >= 1e9) {
            return (number / 1e9).toFixed(2).replace(".", ",") + "B";
        }
        if (number >= 1e6) {
            var millions = number / 1e6;
            var text = millions >= 100 ? String(Math.round(millions)) : millions.toFixed(2);
            return text.replace(".", ",") + "M";
        }
        if (number >= 1e3) {
            return Math.round(number / 1e3) + "K";
        }
        return String(Math.round(number));
    }

    function cleanError(value) {
        var text = String(value || "").replace(/\s+/g, " ").trim();
        if (text.length > 170) {
            text = text.slice(0, 169) + "…";
        }
        return text;
    }

    function applySnapshot(payload) {
        if (!payload || typeof payload !== "object" || !Array.isArray(payload.providers)) {
            return false;
        }
        var daemonBusy = payload.refreshing === true;
        snapshot = payload;
        if (daemonBusy) {
            retryTimer.restart();
        }
        if (!payload.generated_at && !autoRefreshAttempted) {
            autoRefreshAttempted = true;
            initialRefreshTimer.restart();
        }
        return true;
    }

    function pollStatus() {
        if (statusBusy || refreshing) {
            return;
        }
        statusBusy = true;
        activeStatusCommand = statusCommand;
        commandSource.connectSource(activeStatusCommand);
        statusTimeout.restart();
    }

    function refreshNow() {
        if (refreshing) {
            return;
        }
        refreshing = true;
        commandError = "";
        activeRefreshCommand = refreshCommand;
        commandSource.connectSource(activeRefreshCommand);
        refreshTimeout.restart();
    }

    function openSettings() {
        actionSource.connectSource(settingsCommand);
    }

    function collapsePopup() {
        root.expanded = false;
    }

    function processCommand(sourceName, data) {
        var isRefresh = sourceName.indexOf(" refresh ") >= 0;
        var stdout = data && data["stdout"] ? String(data["stdout"]) : "";
        var stderr = data && data["stderr"] ? String(data["stderr"]) : "";
        if (isRefresh) {
            refreshTimeout.stop();
            refreshing = false;
            activeRefreshCommand = "";
        } else {
            statusTimeout.stop();
            statusBusy = false;
            activeStatusCommand = "";
        }
        try {
            commandSource.disconnectSource(sourceName);
        } catch (error) {
        }

        if (stdout.trim().length === 0) {
            if (isRefresh || providers.length === 0) {
                commandError = cleanError(stderr) || "Сервис квот не отвечает.";
            }
            return;
        }

        var payload = null;
        try {
            payload = JSON.parse(stdout);
        } catch (error) {
            commandError = "Некорректный ответ локального сервиса.";
            return;
        }
        if (!applySnapshot(payload)) {
            commandError = "Локальный сервис вернул неожиданные данные.";
            return;
        }
        commandError = "";
    }

    P5Support.DataSource {
        id: commandSource
        engine: "executable"
        connectedSources: []
        onNewData: function(sourceName, data) {
            root.processCommand(sourceName, data);
        }
    }

    P5Support.DataSource {
        id: actionSource
        engine: "executable"
        connectedSources: []
        onNewData: function(sourceName, data) {
            try {
                actionSource.disconnectSource(sourceName);
            } catch (error) {
            }
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: root.nowMs = Date.now()
    }

    Timer {
        id: pollTimer
        interval: 20000
        running: true
        repeat: true
        onTriggered: root.pollStatus()
    }

    Timer {
        id: initialRefreshTimer
        interval: 350
        repeat: false
        onTriggered: root.refreshNow()
    }

    Timer {
        id: retryTimer
        interval: 3000
        repeat: false
        onTriggered: root.pollStatus()
    }

    Timer {
        id: statusTimeout
        interval: 15000
        repeat: false
        onTriggered: {
            if (root.statusBusy) {
                try {
                    commandSource.disconnectSource(root.activeStatusCommand);
                } catch (error) {
                }
                root.statusBusy = false;
                root.activeStatusCommand = "";
                root.commandError = "Сервис квот не отвечает.";
            }
        }
    }

    Timer {
        id: refreshTimeout
        interval: 55000
        repeat: false
        onTriggered: {
            if (root.refreshing) {
                try {
                    commandSource.disconnectSource(root.activeRefreshCommand);
                } catch (error) {
                }
                root.refreshing = false;
                root.activeRefreshCommand = "";
                root.commandError = "Обновление не завершилось вовремя.";
            }
        }
    }

    onExpandedChanged: {
        if (root.expanded) {
            root.pollStatus();
        }
    }

    Component.onCompleted: {
        root.pollStatus();
    }
}
