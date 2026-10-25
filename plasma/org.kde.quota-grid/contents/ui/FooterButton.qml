import QtQuick

Rectangle {
    id: button

    property string label: ""
    property string iconSource: ""
    property bool busy: false
    property bool hovered: false
    signal clicked()

    implicitWidth: 110
    implicitHeight: 38
    radius: 10
    color: hovered && !busy ? "#25282D" : "#1C1E22"
    border.width: 1
    border.color: hovered && !busy ? "#3A3E44" : "#2B2E33"

    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 120 } }

    Row {
        anchors.centerIn: parent
        spacing: 7

        Image {
            id: icon
            width: 13
            height: 13
            anchors.verticalCenter: parent.verticalCenter
            source: button.iconSource
            sourceSize.width: 24
            sourceSize.height: 24
            smooth: true
            opacity: 0.9

            RotationAnimator on rotation {
                running: button.busy
                loops: Animation.Infinite
                from: 0
                to: 360
                duration: 1000
            }

            Connections {
                target: button
                function onBusyChanged() {
                    if (!button.busy) {
                        icon.rotation = 0;
                    }
                }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: button.label
            color: "#D7DADF"
            font.family: "IBM Plex Sans"
            font.pixelSize: 10
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: !button.busy
        hoverEnabled: true
        cursorShape: button.busy ? Qt.ArrowCursor : Qt.PointingHandCursor
        onEntered: button.hovered = true
        onExited: button.hovered = false
        onClicked: button.clicked()
    }
}
