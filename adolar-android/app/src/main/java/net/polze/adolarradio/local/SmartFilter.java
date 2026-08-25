package net.polze.adolarradio.local;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Deterministic offline subset of Adolar's German smart-rule language. */
public final class SmartFilter {
    private static final Pattern FIELD = Pattern.compile(
            "(?iu)\\b(album|alben|albumtitel|titel|tracktitel|songtitel|"
                    + "interpret|interpreten|künstler|kuenstler|artist|genre|genres|"
                    + "jahrzehnt|jahrzehnte|jahr|playcount|wiedergaben|abspielungen|"
                    + "hinzugefügt|hinzugefuegt)\\b"
    );
    private static final Map<String, String> FIELDS = new HashMap<>();

    static {
        alias("album", "album", "alben", "albumtitel");
        alias("title", "titel", "tracktitel", "songtitel");
        alias("artist", "interpret", "interpreten", "künstler", "kuenstler", "artist");
        alias("genre", "genre", "genres");
        alias("decade", "jahrzehnt", "jahrzehnte");
        alias("year", "jahr");
        alias("playcount", "playcount", "wiedergaben", "abspielungen");
        alias("added", "hinzugefügt", "hinzugefuegt");
    }

    private SmartFilter() {
    }

    public static final class ParseException extends Exception {
        ParseException(String message) {
            super(message);
        }
    }

    public static String parseToJson(String input) throws ParseException {
        String text = input == null ? "" : input
                .replace('„', '"').replace('“', '"').trim().replaceAll("\\s+", " ");
        if (text.isEmpty()) throw new ParseException("Bitte eine Smart-Regel eingeben.");
        if (text.length() > 2000) throw new ParseException("Die Regel ist zu lang.");

        List<MatcherSnapshot> fields = new ArrayList<>();
        Matcher matcher = FIELD.matcher(text);
        while (matcher.find()) {
            if (!insideQuotes(text, matcher.start())) {
                fields.add(new MatcherSnapshot(matcher.start(), matcher.end(), matcher.group()));
            }
        }
        if (fields.isEmpty()) {
            throw new ParseException(
                    "Bekannte Felder sind Titel, Album, Interpret, Genre, Jahr, "
                            + "Jahrzehnt, Playcount und Hinzugefügt."
            );
        }

        List<JSONObject> clauses = new ArrayList<>();
        List<String> connectors = new ArrayList<>();
        for (int index = 0; index < fields.size(); index++) {
            MatcherSnapshot field = fields.get(index);
            int end = index + 1 < fields.size() ? fields.get(index + 1).start : text.length();
            String segment = text.substring(field.end, end).trim();
            if (index + 1 < fields.size()) {
                Matcher connector = Pattern.compile("(?iu)\\s+(und|oder)\\s*$").matcher(segment);
                if (!connector.find()) {
                    throw new ParseException("Vor dem nächsten Feld fehlt „und“ oder „oder“.");
                }
                connectors.add(connector.group(1).toLowerCase(Locale.GERMAN));
                segment = segment.substring(0, connector.start()).trim();
            }
            clauses.add(parseClause(FIELDS.get(field.token.toLowerCase(Locale.GERMAN)), segment));
        }

        JSONObject tree = combine(clauses, connectors);
        JSONObject saved = new JSONObject();
        try {
            saved.put("editor_version", 1);
            saved.put("smart_text", text);
            saved.put("interpretation", describe(tree));
            saved.put("rules", tree);
        } catch (JSONException impossible) {
            throw new ParseException("Die Regel konnte nicht gespeichert werden.");
        }
        return saved.toString();
    }

    public static List<LocalTrack> filter(
            List<LocalTrack> tracks, List<TrackState> states, String filterJson
    ) {
        Map<Long, TrackState> stateByTrack = new HashMap<>();
        for (TrackState state : states) stateByTrack.put(state.localTrackId, state);
        List<LocalTrack> result = new ArrayList<>();
        try {
            JSONObject rules = new JSONObject(filterJson).optJSONObject("rules");
            if (rules == null) return result;
            long now = System.currentTimeMillis();
            for (LocalTrack track : tracks) {
                if (matches(rules, track, stateByTrack.get(track.id), now)) result.add(track);
            }
        } catch (JSONException ignored) {
            // Invalid persisted rules resolve to an empty, safe playlist.
        }
        return result;
    }

    private static JSONObject parseClause(String field, String segment) throws ParseException {
        if (field == null) throw new ParseException("Unbekanntes Regelfeld.");
        if ("added".equals(field)) return parseAdded(segment);
        String lower = segment.toLowerCase(Locale.GERMAN);
        String op;
        String values;
        if (lower.matches("^(enthält|enthalten|beinhaltet|beinhalten) nicht .+")) {
            op = "not_contains";
            values = segment.replaceFirst("(?iu)^(enthält|enthalten|beinhaltet|beinhalten)\\s+nicht\\s+", "");
        } else if (lower.matches("^(enthält|enthalten|beinhaltet|beinhalten) .+")) {
            op = "contains";
            values = segment.replaceFirst("(?iu)^(enthält|enthalten|beinhaltet|beinhalten)\\s+", "");
        } else if (lower.matches("^(ist nicht|ist ungleich|ungleich) .+")) {
            op = isNumeric(field) ? "ne" : "not_equals";
            values = segment.replaceFirst("(?iu)^(ist\\s+nicht|ist\\s+ungleich|ungleich)\\s+", "");
        } else if (lower.matches("^(ist )?(größer|groesser|mehr|neuer) als .+")) {
            op = "gt";
            values = segment.replaceFirst("(?iu)^(ist\\s+)?(größer|groesser|mehr|neuer)\\s+als\\s+", "");
        } else if (lower.matches("^(ist )?(kleiner|weniger|älter|aelter) als .+")) {
            op = "lt";
            values = segment.replaceFirst("(?iu)^(ist\\s+)?(kleiner|weniger|älter|aelter)\\s+als\\s+", "");
        } else if (lower.matches("^(ist|gleich|entspricht) .+")) {
            op = isNumeric(field) ? "eq" : "equals";
            values = segment.replaceFirst("(?iu)^(ist|gleich|entspricht)\\s+", "");
        } else if (isNumeric(field) && lower.matches("^-?\\d.*")) {
            op = "eq";
            values = segment;
        } else {
            throw new ParseException("Nach dem Feld fehlt ein Vergleich wie „ist“ oder „enthält“.");
        }
        if ("genre".equals(field)) {
            op = ("not_equals".equals(op) || "not_contains".equals(op))
                    ? "not_contains" : "contains";
        }
        if (!isNumeric(field) && ("gt".equals(op) || "lt".equals(op))) {
            throw new ParseException("Größer/kleiner ist nur für Zahlenfelder erlaubt.");
        }

        SplitValues split = splitValues(values);
        JSONArray rules = new JSONArray();
        for (String value : split.values) {
            JSONObject rule = new JSONObject();
            try {
                rule.put("field", field);
                rule.put("op", op);
                rule.put("value", isNumeric(field) ? parseNumber(value) : unquote(value));
                rules.put(rule);
            } catch (JSONException impossible) {
                throw new ParseException("Regel konnte nicht erstellt werden.");
            }
        }
        if (rules.length() == 0) throw new ParseException("Der Regelwert fehlt.");
        if (rules.length() == 1) return rules.optJSONObject(0);
        String mode = isNumeric(field) && "eq".equals(op) ? "any" : split.mode;
        return group(mode, rules);
    }

    private static JSONObject parseAdded(String segment) throws ParseException {
        Matcher matcher = Pattern.compile(
                "(?iu)^(?:ist\\s+)?(vor|innerhalb\\s+der\\s+letzten)\\s+"
                        + "(\\d+)\\s+(tag|tage|tagen|woche|wochen|monat|monate|monaten|"
                        + "jahr|jahre|jahren)$"
        ).matcher(segment.trim());
        if (!matcher.matches()) {
            throw new ParseException("Beispiel: Hinzugefügt innerhalb der letzten 2 Monate.");
        }
        String unitText = matcher.group(3).toLowerCase(Locale.GERMAN);
        String unit = unitText.startsWith("tag") ? "days"
                : unitText.startsWith("woch") ? "weeks"
                : unitText.startsWith("monat") ? "months" : "years";
        JSONObject rule = new JSONObject();
        try {
            rule.put("field", "added");
            rule.put("op", matcher.group(1).toLowerCase(Locale.GERMAN).startsWith("vor")
                    ? "before" : "within_last");
            rule.put("value", Integer.parseInt(matcher.group(2)));
            rule.put("unit", unit);
        } catch (JSONException impossible) {
            throw new ParseException("Regel konnte nicht erstellt werden.");
        }
        return rule;
    }

    private static JSONObject combine(List<JSONObject> clauses, List<String> connectors)
            throws ParseException {
        List<List<JSONObject>> terms = new ArrayList<>();
        terms.add(new ArrayList<>());
        terms.get(0).add(clauses.get(0));
        for (int index = 0; index < connectors.size(); index++) {
            if ("oder".equals(connectors.get(index))) terms.add(new ArrayList<>());
            terms.get(terms.size() - 1).add(clauses.get(index + 1));
        }
        JSONArray any = new JSONArray();
        for (List<JSONObject> term : terms) {
            if (term.size() == 1) any.put(term.get(0));
            else any.put(group("all", new JSONArray(term)));
        }
        JSONObject root = terms.size() == 1
                ? (terms.get(0).size() == 1 ? terms.get(0).get(0) : group("all", any))
                : group("any", any);
        if (!root.has("rules")) {
            JSONArray single = new JSONArray();
            single.put(root);
            root = group("all", single);
        }
        return root;
    }

    private static boolean matches(
            JSONObject node, LocalTrack track, TrackState state, long now
    ) throws JSONException {
        JSONArray children = node.optJSONArray("rules");
        if (children != null) {
            boolean all = "all".equals(node.optString("mode", "all"));
            for (int index = 0; index < children.length(); index++) {
                boolean child = matches(children.getJSONObject(index), track, state, now);
                if (all && !child) return false;
                if (!all && child) return true;
            }
            return all;
        }
        String field = node.getString("field");
        String op = node.getString("op");
        if ("added".equals(field)) {
            long amount = node.getLong("value") * unitMillis(node.optString("unit"));
            return "before".equals(op) ? track.addedAt < now - amount : track.addedAt >= now - amount;
        }
        if (isNumeric(field)) {
            long actual;
            if ("playcount".equals(field)) actual = state == null ? 0 : state.playCount;
            else if ("decade".equals(field)) actual = track.year == null ? 0 : (track.year / 10) * 10;
            else actual = track.year == null ? 0 : track.year;
            long expected = node.getLong("value");
            if ("gt".equals(op)) return actual > expected;
            if ("lt".equals(op)) return actual < expected;
            if ("ne".equals(op)) return actual != expected;
            return actual == expected;
        }
        String actual = "title".equals(field) ? track.title
                : "artist".equals(field) ? track.artist
                : "album".equals(field) ? track.album : track.genre;
        actual = actual == null ? "" : actual.toLowerCase(Locale.GERMAN);
        String expected = node.optString("value").toLowerCase(Locale.GERMAN);
        if ("not_contains".equals(op)) return !actual.contains(expected);
        if ("not_equals".equals(op)) return !actual.equals(expected);
        if ("equals".equals(op)) return actual.equals(expected);
        return actual.contains(expected);
    }

    private static String describe(JSONObject tree) {
        return tree.toString();
    }

    private static SplitValues splitValues(String text) throws ParseException {
        List<String> values = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        Character quote = null;
        String mode = "any";
        String lower = text.toLowerCase(Locale.GERMAN);
        for (int index = 0; index < text.length();) {
            char character = text.charAt(index);
            if (character == '\'' || character == '"') {
                quote = quote != null && quote == character ? null : quote == null ? character : quote;
                current.append(character);
                index++;
                continue;
            }
            String separator = null;
            if (quote == null && character == ',') separator = ",";
            else if (quote == null && wordAt(lower, index, " oder ")) separator = " oder ";
            else if (quote == null && wordAt(lower, index, " und ")) {
                separator = " und ";
                mode = "all";
            }
            if (separator != null) {
                String value = unquote(current.toString());
                if (!value.isEmpty()) values.add(value);
                current.setLength(0);
                index += separator.length();
            } else {
                current.append(character);
                index++;
            }
        }
        String value = unquote(current.toString());
        if (!value.isEmpty()) values.add(value);
        if (values.isEmpty()) throw new ParseException("Der Regelwert fehlt.");
        return new SplitValues(values, mode);
    }

    private static JSONObject group(String mode, JSONArray rules) throws ParseException {
        JSONObject group = new JSONObject();
        try {
            group.put("mode", mode);
            group.put("rules", rules);
        } catch (JSONException impossible) {
            throw new ParseException("Regelgruppe konnte nicht erstellt werden.");
        }
        return group;
    }

    private static int parseNumber(String value) throws ParseException {
        Matcher matcher = Pattern.compile("^-?\\d+").matcher(unquote(value));
        if (!matcher.find()) throw new ParseException("Zahlenfeld benötigt eine Zahl.");
        try {
            return Integer.parseInt(matcher.group());
        } catch (NumberFormatException error) {
            throw new ParseException("Die Zahl ist zu groß.");
        }
    }

    private static long unitMillis(String unit) {
        if ("weeks".equals(unit)) return 7L * 86_400_000L;
        if ("months".equals(unit)) return 30L * 86_400_000L;
        if ("years".equals(unit)) return 365L * 86_400_000L;
        return 86_400_000L;
    }

    private static boolean isNumeric(String field) {
        return "year".equals(field) || "decade".equals(field) || "playcount".equals(field);
    }

    private static boolean insideQuotes(String text, int end) {
        Character quote = null;
        for (int index = 0; index < end; index++) {
            char character = text.charAt(index);
            if (character == '\'' || character == '"') {
                quote = quote != null && quote == character ? null : quote == null ? character : quote;
            }
        }
        return quote != null;
    }

    private static boolean wordAt(String text, int index, String word) {
        return index + word.length() <= text.length()
                && text.regionMatches(index, word, 0, word.length());
    }

    private static String unquote(String value) {
        String clean = value.trim().replaceAll("^[,.;:]+|[,.;:]+$", "").trim();
        if (clean.length() >= 2 && (clean.charAt(0) == '"' || clean.charAt(0) == '\'')
                && clean.charAt(clean.length() - 1) == clean.charAt(0)) {
            clean = clean.substring(1, clean.length() - 1).trim();
        }
        return clean;
    }

    private static void alias(String field, String... aliases) {
        for (String value : aliases) FIELDS.put(value, field);
    }

    private static final class MatcherSnapshot {
        final int start;
        final int end;
        final String token;

        MatcherSnapshot(int start, int end, String token) {
            this.start = start;
            this.end = end;
            this.token = token;
        }
    }

    private static final class SplitValues {
        final List<String> values;
        final String mode;

        SplitValues(List<String> values, String mode) {
            this.values = values;
            this.mode = mode;
        }
    }
}
