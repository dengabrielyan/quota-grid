import QtQuick
import QtQuick.Layouts

Item {
    id: compact

    property var root: null
    property bool pressed: false
    property bool hovered: false
    signal activated()

    readonly property int count: root ? root.providers.length : 0
    readonly property int itemSize: 26
    readonly property int gap: 4
    readonly property int paddingX: 6

    implicitWidth: Math.max(34, count * itemSize + Math.max(0, count - 1) * gap + paddingX * 2)
    implicitHeight: 30

    Layout.minimumWidth: implicitWidth
    Layout.preferredWidth: implicitWidth
    Layout.maximumWidth: implicitWidth
    Layout.minimumHeight: implicitHeight
    Layout.preferredHeight: implicitHeight
    Layout.maximumHeight: implicitHeight

    Rectangle {
        anchors.fill: parent
        radius: 9
        color: compact.hovered ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(1, 1, 1, 0.025)
        border.width: 1
        border.color: compact.hovered
            ? Qt.rgba(1, 1, 1, 0.12)
            : Qt.rgba(1, 1, 1, 0.055)
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    Row {
        id: badgeRow
        anchors.centerIn: parent
        spacing: compact.gap

        Repeater {
            model: compact.root ? compact.root.providers : []

            delegate: CompactBadge {
                width: compact.itemSize
                height: compact.itemSize
                provider: modelData
                root: compact.root
            }
        }
    }

    Image {
        visible: compact.count === 0
        anchors.centerIn: parent
        width: 18
        height: 18
        source: Qt.resolvedUrl("../icons/quota-grid-mark.svg")
        sourceSize.width: 32
        sourceSize.height: 32
        opacity: 0.5
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: compact.hovered = true
        onExited: compact.hovered = false
        onPressed: compact.pressed = true
        onReleased: compact.pressed = false
        onCanceled: compact.pressed = false
        onClicked: compact.activated()
    }

    scale: compact.pressed ? 0.96 : 1
    Behavior on scale { NumberAnimation { duration: 100 } }
}
