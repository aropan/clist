<?php

require_once dirname(__FILE__) . "/../../config.php";

global $URL, $RID, $HOST, $TIMEZONE, $contests;

$page = 0;
for (;;) {
    $page += 1;
    $url = "$URL?page=$page";
    $page_html = curlexec($url);
    if (!preg_match('#<script[^>]*id="lentille-context"[^>]*>(?P<json>[^<]*)</script>#', $page_html, $match)) {
        trigger_error("Failed to find lentille-context on url $url", E_USER_WARNING);
        break;
    }
    $data = json_decode($match['json'], true);
    if (!is_array($data)) {
        trigger_error("Failed to decode lentille-context json from $url", E_USER_WARNING);
        break;
    }

    $contests_info = get_item($data, ["data", "contests"]);
    $contests_data = get_item($contests_info, "result");
    if (!$contests_data || !$contests_info) {
        trigger_error("Failed to parse contests data = " . json_encode($data), E_USER_WARNING);
        break;
    }
    $total_pages = $contests_info["perPage"] ? $contests_info["count"] / $contests_info["perPage"] : 0;

    foreach ($contests_data as $c) {
        $key = array_pop_assoc($c, "id");
        $title = trim(array_pop_assoc($c, "name"));
        $kind = null;
        $standings_kind = null;

        $rule_type = get_item($c, "method");
        if ($rule_type) {
            $c["rule_type"] = $rule_type;
        }
        if ($rule_type == 2) {
            $kind = "ICPC";
            $standings_kind = "icpc";
        } elseif ($rule_type == 4) {
            $kind = "IOI";
            $standings_kind = "scoring";
        } elseif ($rule_type == 1) {
            $kind = "OI";
            $standings_kind = "scoring";
        } elseif ($rule_type == 5) {
            $kind = "CF";
            $standings_kind = "cf";
        } elseif ($rule_type == 3) {
            $kind = "LEDO";
            $standings_kind = "scoring";
        }

        $tags = [];
        $rated = get_item($c, "rated");
        if ($rated == 3) {
            // 计入等级分 — counts for the competitive rating (in the CF sense).
            $tags[] = "rated";
        } elseif ($rated == 1) {
            // 计入咕值 — counts for Luogu's participation score ("咕值"), not the rating.
            $tags[] = "guzhi";
        }
        if ($kind) {
            $tags[] = strtolower($kind);
        }
        if (get_item($c, "squad")) {
            $tags[] = "squad";
        }

        if ($tags) {
            $title .= " [" . implode(", ", $tags) . "]";
        }

        $contests[] = [
            "start_time" => array_pop_assoc($c, "startTime"),
            "end_time" => array_pop_assoc($c, "endTime"),
            "title" => $title,
            "url" => url_merge($URL, "/contest/" . $key),
            "rid" => $RID,
            "host" => $HOST,
            "timezone" => $TIMEZONE,
            "standings_kind" => $standings_kind,
            "key" => $key,
            "info" => ["parse" => $c],
        ];
    }

    if ($page >= $total_pages || !isset($_GET["parse_full_list"])) {
        break;
    }
}
