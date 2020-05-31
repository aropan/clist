<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);

    preg_match_all('
#
>\s*(?:[0-9]{4}\s+)?(?P<title>[-\sa-zA-Z0-9\<]+)\s*(?:\([^<:]*\)\s*)?
(?:<[^>]*>|:)\s*
(?P<start_time>[^<,"]*,\s*[0-9]{4}[^-\(<]*)[^<]*
#x
        ',
        $page,
        $matches,
        PREG_SET_ORDER
    );

    foreach ($matches as $match)
    {
        $title = $match['title'];
        $start_time = $match['start_time'];
        if (preg_match('#\((?P<duration>[0-9]+)[^-<>\)]*\)#', $match[0], $m)) {
            $duration = $m['duration'] * 60;
        } else {
            $duration = '00:00';
        }
        $start_time = preg_replace('/\s*-[^,]*[0-9]+[^,]*,/', '', $start_time);
        $start_time = preg_replace('/[A-Z]{3,}\s*$/', '', $start_time);
        $contests[] = array(
            'start_time' => $start_time,
            'duration' => $duration,
            'title' => $title,
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => "$title " . date('Y', strtotime($start_time))
        );
    }
    if ($RID == -1) {
        print_r($contests);
    }
?>
