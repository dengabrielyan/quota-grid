import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import org.kde.kirigami as Kirigami

Item {
    id: view

    property var root: null

    readonly property int providerCount: root && root.providers ? root.providers.length : 0
    readonly property int cardsHeight: {
        var total = 0;
        for (var i = 0; i < providerCount; i++) {
            total += view.providerCardHeight(root.providers[i]);
        }
        return total + Math.max(0, providerCount - 1) * 10;
    }
    readonly property int desiredHeight: Math.max(730, 148 + cardsHeight)
    readonly property color syncTone: root ? root.syncColor : "#858C96"

    function providerCardHeight(provider) {
        var count = provider && provider.windows ? Math.min(4, provider.windows.length) : 0;
        return count > 2 ? 154 + (count - 2) * 49 : 154;
    }

    implicitWidth: 440
    implicitHeight: desiredHeight
    width: implicitWidth
    height: implicitHeight

    // AppletPopup normally draws its own rectangular backplate. Hint 0 is its
    // internal no-background value, leaving only our rounded card and shadow.
    function configurePopupWindow() {
        var popup = Window.window;
        if (!popup) return;
        try {
            popup.backgroundHints = 0;
        } catch (error) {
        }
        try {
            popup.margin = 24;
        } catch (error) {
        }
    }

    Component.onCompleted: Qt.callLater(configurePopupWindow)

    Timer {
        interval: 300
        repeat: false
        running: true
        onTriggered: view.configurePopupWindow()
    }

    Layout.minimumWidth: 440
    Layout.preferredWidth: 440
    Layout.minimumHeight: desiredHeight
    Layout.preferredHeight: desiredHeight


    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.margins: -4
        radius: 18
        clip: true
        color: Kirigami.Theme.backgroundColor

        Item {
            id: content
            anchors.fill: parent
            anchors.margins: 18

            Item {
                id: header
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 46

                Image {
                    id: brandMark
                    x: 0
                    y: 4
                    width: 30
                    height: 30
                    source: Qt.resolvedUrl("../icons/quota-grid-mark.svg")
                    sourceSize.width: 64
                    sourceSize.height: 64
                    smooth: true
                }

                Column {
                    x: 40
                    y: 1
                    spacing: 2

                    Text {
                        text: "AI Quotas"
                        color: Kirigami.Theme.textColor
                        font.family: "IBM Plex Sans"
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: view.root
                            ? view.root.providerCountLabel + "  ·  " + view.root.lastUpdatedLabel
                            : ""
                        color: Kirigami.Theme.disabledTextColor
                        font.family: "IBM Plex Sans"
                        font.pixelSize: 10
                    }
                }

                Rectangle {
                    id: syncPill
                    height: 22
                    width: syncRow.width + 20
                    radius: 11
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    color: Qt.rgba(view.syncTone.r, view.syncTone.g, view.syncTone.b, 0.08)
                    border.width: 1
                    border.color: Qt.rgba(view.syncTone.r, view.syncTone.g, view.syncTone.b, 0.18)

                    Row {
                        id: syncRow
                        anchors.centerIn: parent
                        spacing: 6

                        Rectangle {
                            width: 5
                            height: 5
                            radius: 2.5
                            anchors.verticalCenter: parent.verticalCenter
                            color: view.syncTone
                        }

                        Text {
                            text: view.root ? view.root.syncLabel : "IDLE"
                            color: view.syncTone
                            font.family: "IBM Plex Sans"
                            font.pixelSize: 8
                            font.weight: Font.DemiBold
                            font.letterSpacing: 0.7
                        }
                    }
                }
            }

            Column {
                id: cardList
                anchors.top: header.bottom
                anchors.topMargin: 14
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 10
                visible: view.providerCount > 0

                Repeater {
                    model: view.root ? view.root.providers : []

                    delegate: ProviderCard {
                        width: cardList.width
                        height: view.providerCardHeight(modelData)
                        provider: modelData
                        root: view.root
                    }
                }
            }

            Item {
                id: emptyState
                anchors.top: header.bottom
                anchors.bottom: footer.top
                anchors.left: parent.left
                anchors.right: parent.right
                visible: view.providerCount === 0

                Column {
                    width: Math.min(300, parent.width)
                    anchors.centerIn: parent
                    spacing: 7

                    Image {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 40
                        height: 40
                        source: Qt.resolvedUrl("../icons/quota-grid-mark.svg")
                        sourceSize.width: 64
                        sourceSize.height: 64
                        smooth: true
                        opacity: 0.35
                    }

                    Text {
                        width: parent.width
                        text: {
                            if (!view.root) return "";
                            if (view.root.refreshing) return "Синхронизация";
                            if (view.root.commandError.length > 0) return "Сервис недоступен";
                            return "Нет активных сессий";
                        }
                        color: view.root && view.root.commandError.length > 0
                            ? "#FF8D9E"
                            : "#EDF1F3"
                        font.family: "IBM Plex Sans"
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Text {
                        width: parent.width
                        text: {
                            if (!view.root) return "";
                            if (view.root.refreshing) {
                                return "Считываю локальные сессии Claude Code, Codex и ZCode.";
                            }
                            if (view.root.commandError.length > 0) {
                                return view.root.commandError;
                            }
                            return "Авторизуйте Codex, Claude Code или ZCode и обновите данные.";
                        }
                        color: view.root && view.root.commandError.length > 0
                            ? Qt.rgba(255 / 255, 141 / 255, 158 / 255, 0.78)
                            : "#858C96"
                        font.family: "IBM Plex Sans"
                        font.pixelSize: 10
                        lineHeight: 1.2
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Text {
                        visible: view.root && !view.root.refreshing && view.root.commandError.length === 0
                        width: parent.width
                        text: "quota-manager doctor"
                        color: "#63707B"
                        font.family: "IBM Plex Mono"
                        font.pixelSize: 8
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }

            Row {
                id: footer
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 38
                spacing: 8

                FooterButton {
                    width: (footer.width - footer.spacing * 2) / 3
                    height: footer.height
                    label: "Обновить"
                    iconSource: Qt.resolvedUrl("../icons/refresh.svg")
                    busy: view.root ? view.root.refreshing : false
                    onClicked: if (view.root) view.root.refreshNow()
                }

                FooterButton {
                    width: (footer.width - footer.spacing * 2) / 3
                    height: footer.height
                    label: "Настройки"
                    iconSource: Qt.resolvedUrl("../icons/gear.svg")
                    onClicked: if (view.root) view.root.openSettings()
                }

                FooterButton {
                    width: (footer.width - footer.spacing * 2) / 3
                    height: footer.height
                    label: "Закрыть"
                    iconSource: Qt.resolvedUrl("../icons/close.svg")
                    onClicked: if (view.root) view.root.collapsePopup()
                }
            }
        }
    }
}
