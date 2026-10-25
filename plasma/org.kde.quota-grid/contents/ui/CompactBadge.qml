import QtQuick

Item {
    id: badge

    property var provider: null
    property var root: null

    readonly property bool hasError: provider && provider.status !== "ok"
    readonly property color accentColor: root && provider ? root.accentFor(provider.id) : "#6CF5D5"
    readonly property real remainingPercent: {
        if (!root || !provider) return 100;
        var value = root.minimumRemaining(provider);
        if (value === null || !isFinite(Number(value))) return 100;
        return Math.max(0, Math.min(100, Number(value)));
    }
    readonly property real usedPercent: 100 - remainingPercent
    readonly property color progressColor: {
        if (remainingPercent <= 0.5) return "#FF6B7D";
        if (remainingPercent <= 15) return "#F5B95F";
        return accentColor;
    }

    implicitWidth: 26
    implicitHeight: 26
    opacity: hasError ? 0.55 : 1

    Canvas {
        id: ring
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d");
            ctx.clearRect(0, 0, width, height);
            var cx = width / 2;
            var cy = height / 2;
            var radius = Math.min(width, height) / 2 - 2.4;
            var start = -Math.PI / 2;

            ctx.fillStyle = Qt.rgba(badge.accentColor.r, badge.accentColor.g, badge.accentColor.b, 0.06);
            ctx.beginPath();
            ctx.arc(cx, cy, radius + 1.1, 0, Math.PI * 2);
            ctx.fill();

            ctx.strokeStyle = Qt.rgba(badge.accentColor.r, badge.accentColor.g, badge.accentColor.b, 0.32);
            ctx.lineWidth = 1.2;
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.stroke();

            if (badge.usedPercent > 0.2) {
                ctx.strokeStyle = badge.progressColor;
                ctx.lineWidth = 2;
                ctx.lineCap = "round";
                ctx.beginPath();
                ctx.arc(cx, cy, radius, start, start + Math.PI * 2 * badge.usedPercent / 100);
                ctx.stroke();
            }
        }

        Connections {
            target: badge
            function onUsedPercentChanged() { ring.requestPaint(); }
            function onAccentColorChanged() { ring.requestPaint(); }
            function onProgressColorChanged() { ring.requestPaint(); }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Image {
        anchors.centerIn: parent
        readonly property int logoSize: badge.provider && badge.provider.id === "zcode" ? 12 : 14
        width: logoSize
        height: logoSize
        source: badge.provider
            ? Qt.resolvedUrl("../icons/providers/" + badge.provider.icon + ".png")
            : ""
        sourceSize.width: 32
        sourceSize.height: 32
        smooth: true
    }

    Rectangle {
        visible: badge.hasError
        width: 5
        height: 5
        radius: 2.5
        color: "#FF6B7D"
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: -1
        anchors.topMargin: -1
    }
}
