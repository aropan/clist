<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);

    if (!preg_match("#<title>[^<]*-\s*([^<]*)</title>#", $page, $match)) {
        return;
    }
    list($title, $year) = explode(" ", $match[1], 2);

    preg_match_all("#<strong>(?P<title>[^<]*)</strong>:\s*(?P<start_time>[^.;<]*)#xi", $page, $matches, PREG_SET_ORDER);

    if (preg_match('#<h[^>]*class="[^"]*alignRight[^"]*"[^>]*>(?<title>[^:]*)#', $page, $match)) {
        $rtitle = $match['title'];
        preg_match('#secondsBefore\s*=\s*(?<before>[0-9]+)#', $page, $match);
        $rtime = time() + intval($match['before']);
        $rtime = intval(round($rtime / 3600) * 3600);
    }

    $sandbox_idx = -1;
    $idx = 0;
    foreach ($matches as $match)
    {
        $round = $match['title'];
        $start_time = $match['start_time'];

        if (preg_match('#from\s*([^0-9]+\s*[0-9]+)$#', $start_time, $match)) {
            $start_time = $match[1];
        }

        if (preg_match('#[0-9]+\s*-\s*[0-9]+#', $start_time)) {
            $end_time = preg_replace('#[0-9]+\s*-\s*([0-9]+)#', '\1', $start_time) . " " . $year;
            $start_time = preg_replace('#([0-9]+)\s*-\s*[0-9]+#', '\1', $start_time) . " " . $year;
        } else {
            $end_time = $start_time;
        }

        if (substr_count($start_time, " ") > 5) {
            continue;
        }

        $start_time = isset($rtitle) && $round == $rtitle? $rtime : $start_time;

        if ($round == "Sandbox") {
            $sandbox_idx = count($contests);
        } else if ($sandbox_idx !== -1) {
            $contests[$sandbox_idx]['end_time'] = $end_time;
        }

        $idx += 1;

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title . '. ' . $round,
            'url' => $HOST_URL,
            'host' => $HOST,
            'key' => $title . '. ' . $round,
            'rid' => $RID,
            'standings_url' => url_merge($HOST_URL, "/contest/$idx/standings"),
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
