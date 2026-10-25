import QtQuick

Rectangle {
    id: card

    property var provider: null
    property var root: null
    property bool hovered: false

    readonly property var windows: {
        if (!provider || !provider.windows) return [];
        return provider.windows.length > 4 ? provider.windows.slice(0, 4) : provider.windows;
    }
    readonly property color accentColor: root && provider ? root.accentFor(provider.id) : "#6CF5D5"
    readonly property string stateLabel: root ? root.providerStateLabel(provider) : ""
    readonly property color stateColor: root ? root.stateColor(stateLabel) : accentColor
    readonly property bool hasError: !provider || provider.status !== "ok"
    readonly property string secondaryText: {
        if (!provider) return "";
        if (hasError && provider.error) return provider.error;
        var parts = [];
        if (provider.account) parts.push(provider.account);
        if (provider.note) parts.push(provider.note);
        return parts.join(" · ");
    }

    readonly property int rowCount: Math.min(4, windows.length)
    implicitHeight: 154 + Math.max(0, rowCount - 2) * 49
    radius: 16
    color: hovered ? "#1E2024" : "#1B1D21"
    border.width: 1
    border.color: hovered
        ? Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.34)
        : "#292C31"

    Behavior on color { ColorAnimation { duration: 140 } }
    Behavior on border.color { ColorAnimation { duration: 140 } }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onEntered: card.hovered = true
        onExited: card.hovered = false
    }

    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 12
        height: 34

        Rectangle {
            id: iconCircle
            width: 34
            height: 34
            radius: 9
            anchors.verticalCenter: parent.verticalCenter
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(card.accentColor.r, card.accentColor.g, card.accentColor.b, 0.32)

            Image {
                readonly property real logoSize: card.provider && card.provider.id === "zcode" ? 26 : 32
                width: logoSize
                height: logoSize
                anchors.centerIn: parent
                source: card.provider
                    ? Qt.resolvedUrl("../icons/providers/" + card.provider.icon + ".png")
                    : ""
                sourceSize.width: 64
                sourceSize.height: 64
                fillMode: Image.PreserveAspectFit
                smooth: true
                opacity: card.hasError ? 0.55 : 1
            }
        }

        Row {
            id: stateRow
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5

            Rectangle {
                width: 4
                height: 4
                radius: 2
                anchors.verticalCenter: parent.verticalCenter
                color: card.stateColor
            }

            Text {
                text: card.stateLabel
                color: card.stateColor
                font.family: "IBM Plex Sans"
                font.pixelSize: 8
                font.weight: Font.DemiBold
                font.letterSpacing: 0.8
            }
        }

        Column {
            anchors.left: iconCircle.right
            anchors.leftMargin: 9
            anchors.right: stateRow.left
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2

            Text {
                width: parent.width
                text: card.provider ? card.provider.name : ""
                color: "#F0F2F4"
                font.family: "IBM Plex Sans"
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Text {
                width: parent.width
                text: card.secondaryText
                color: card.hasError
                    ? Qt.rgba(card.stateColor.r, card.stateColor.g, card.stateColor.b, 0.9)
                    : "#858C96"
                font.family: "IBM Plex Sans"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }
    }

    Column {
        id: rows
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 8
        spacing: 8

        Repeater {
            model: card.windows

            delegate: LimitRow {
                width: rows.width
                height: 41
                windowData: modelData
                root: card.root
                accentColor: card.accentColor
            }
        }

        Text {
            visible: card.windows.length === 0
            width: rows.width
            text: card.provider && card.provider.error
                ? card.provider.error
                : "Нет активных окон лимита"
            color: "#858C96"
            font.family: "IBM Plex Sans"
            font.pixelSize: 10
            wrapMode: Text.WordWrap
        }
    }
}
