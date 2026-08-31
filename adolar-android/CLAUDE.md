# Adolar Next Android

Dieses Repository ist der eigenstaendige Android-Client fuer Adolar Next.

## Entwicklung

- Gradle Wrapper verwenden, nicht eine global installierte Gradle-Version.
- Debug-Build lokal mit `./gradlew testDebugUnitTest lintDebug assembleDebug` pruefen.
- Der Wrapper-JAR unter `gradle/wrapper/gradle-wrapper.jar` gehoert ins Repo, damit CI und frische Checkouts ohne lokale Gradle-Installation funktionieren.
- `local.properties`, `.gradle/`, `build/`, `app/build/` und signierende Keystores bleiben lokal.

## Android-Kontext

- Java-Namespace bleibt aktuell `net.polze.adolarradio`; die installierbare App-ID ist `net.polze.adolarnext`.
- `minSdk` ist 23. Bei neuen APIs entweder kompatible Alternativen verwenden oder bewusst desugaring/SDK-Anhebung entscheiden.
- Cleartext HTTP ist absichtlich erlaubt, weil Adolar oft auf lokalen NAS-/LAN-URLs laeuft.
