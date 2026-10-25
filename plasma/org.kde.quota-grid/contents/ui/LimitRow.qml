import QtQuick

Item {
    id: row

    property var windowData: null
    property var root: null
    property color accentColor: "#6CF5D5"

    readonly property real usedPercent: windowData
        ? Math.max(0, Math.min(100, Number(windowData.used_percent) || 0))
        : 0
    readonly property real remainingPercent: windowData
        ? Math.max(0, Math.min(100, Number(windowData.remaining_percent) || 0))
        : 0
    readonly property bool tokenWindow: windowData && windowData.unit === "token"
    readonly property color remainingColor: {
        if (remainingPercent <= 0.5) return "#FF6B7D";
        if (remainingPercent <= 15) return "#F5B95F";
        return "#838B95";
    }
    readonly property string labelText: {
        if (!windowData) return "";
        if (windowData.period === "rolling_5h") return "5-часовой лимит";
        if (windowData.period === "weekly") return "Недельный лимит";
        var text = windowData.title || "Лимит";
        if (windowData.period === "daily") {
            text += " · день";
        } else if (windowData.period === "one_time") {
            text += " · бонус";
        }
        return text;
    }
    readonly property string tokenValueText: {
        if (!windowData || !root) return "";
        var used = Number(windowData.used_value);
        var limit = Number(windowData.limit_value);
        if (!isFinite(used) || !isFinite(limit)) return "";
        return root.formatTokens(used) + " / " + root.formatTokens(limit);
    }
    readonly property string remainingText: {
        if (!windowData || !root) return "";
        if (tokenWindow) {
            return "осталось " + root.formatTokens(windowData.remaining_value);
        }
        return "осталось " + Math.round(remainingPercent) + "%";
    }
    readonly property string resetText: {
        if (!root || !windowData) return "";
        var text = root.resetLabel(windowData.resets_at);
        if (windowData.period === "one_time") {
            text = text.replace("сброс", "истекает");
        }
        return text;
    }

    implicitHeight: 41

    Item {
        id: topLine
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 18

        Row {
            id: rightGroup
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            Text {
                visible: row.tokenWindow
                anchors.verticalCenter: parent.verticalCenter
                text: row.tokenValueText
                color: "#8C949E"
                font.family: "IBM Plex Mono"
                font.pixelSize: 9
            }

            Rectangle {
                width: pillText.implicitWidth + 14
                height: 18
                radius: 9
                color: Qt.rgba(row.accentColor.r, row.accentColor.g, row.accentColor.b, 0.13)
                border.width: 1
                border.color: Qt.rgba(row.accentColor.r, row.accentColor.g, row.accentColor.b, 0.18)

                Text {
                    id: pillText
                    anchors.centerIn: parent
                    text: Math.round(row.usedPercent) + "%"
                    color: row.accentColor
                    font.family: "IBM Plex Sans"
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                }
            }
        }

        Text {
            anchors.left: parent.left
            anchors.right: rightGroup.left
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: row.labelText
            color: "#D4D7DC"
            font.family: "IBM Plex Sans"
            font.pixelSize: 11
            elide: Text.ElideRight
        }
    }

    Rectangle {
        id: track
        anchors.top: topLine.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        height: 6
        radius: 3
        color: Qt.rgba(1, 1, 1, 0.075)

        Rectangle {
            width: Math.max(0, track.width * row.usedPercent / 100)
            height: parent.height
            radius: parent.radius
            color: row.accentColor
            Behavior on width { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
        }
    }

    Item {
        id: metaLine
        anchors.top: track.bottom
        anchors.topMargin: 3
        anchors.left: parent.left
        anchors.right: parent.right
        height: 10

        Text {
            anchors.left: parent.left
            width: parent.width * 0.5
            text: row.remainingText
            color: row.remainingColor
            font.family: "IBM Plex Sans"
            font.pixelSize: 9
            elide: Text.ElideRight
        }

        Text {
            anchors.right: parent.right
            width: parent.width * 0.48
            text: row.resetText
            color: "#717984"
            font.family: "IBM Plex Sans"
            font.pixelSize: 9
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
        }
    }
}
