<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);
    preg_match_all(
        '#<li>' .
        '(?P<date>[a-zA-Z]+\s*[0-9]+\s*)' .
        '(?:&ndash;[0-9]+\s*)?,\s*(?P<year>[0-9]+)\s*' .
        '(?:&mdash;\s*)?(?P<title>[^,\.]*)[,\.]?\s*</li>\s*' .
        '(?P<table><table.*?</table>)?#s',
        $page,
        $matches
    );

    foreach ($matches[0] as $i => $value) {
        $title = ucwords(trim($matches['title'][$i]));
        $year = trim($matches['year'][$i]);
        $date = trim($matches['date'][$i]) . ' ' . $year;

        $contest = array(
            'title' => $title,
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $title . ' ' . $year
        );

        $table = $matches['table'][$i];
        if ($table) {
            if (
                preg_match('#<td[^>]*>\s*Start:\s*</td>.*?>(?P<val>[0-9]+:[0-9]+)\s*(?<tz>[^<]*)<#is', $table, $start) &&
                preg_match('#<td[^>]*>\s*End:\s*</td>.*?>(?P<val>[0-9]+:[0-9]+)[^<]*<#is', $table, $end)
            ){
                $contest['timezone'] = $start['tz']? $start['tz'] : $TIMEZONE;
                $contest['start_time'] = $date . ' ' . $start['val'];
                $contest['end_time'] = $date . ' ' . $end['val'];
            } else if (
                preg_match('#<td[^>]*>(?P<date>[^<]*\s*[0-9]{4})</td>.*?>(?P<val>[0-9]+:[0-9]+[^<]*)(</[^>]*>)*\s*<td[^>]*>[^<]*begins<#is', $table, $start) &&
                preg_match('#<td[^>]*>(?P<date>[^<]*\s*[0-9]{4})</td>\s*<td[^>]*>\s*<a[^>]*>(?P<val>[0-9]+:[0-9]+[^<]*)(</[^>]*>)*\s*<td[^>]*>[^<]*ends<#is', $table, $end)
            ){
                $timezone = preg_match('/>Time \(([^\)]*)\)</', $table, $match)? $match[1] : $TIMEZONE;
                $contest['timezone'] = $timezone;
                $contest['start_time'] = $start['date'] . ' ' . $start['val'];
                $contest['end_time'] = $end['date'] . ' ' . $end['val'];
            }
        }

        if (!isset($contest['start_time'])) {
            $contest['start_time'] = $date;
        }

        if (!isset($contest['end_time'])) {
            $contest['duration'] = '00:00';
        }

        $contests[] = $contest;
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
