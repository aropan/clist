<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://usaco.org/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);

    if (!preg_match('#(\d{4})-(\d{4}) Schedule#', $page, $match)) return;
    list(, $start_year, $end_year) = $match;

    preg_match_all("#(?<month>[^\s]+)\s(?<start_date>\d+)-(?<end_date>\d+):(?<title>[^<]*)#", $page, $matches);

    if (count($matches[0]))
        $mindate = strtotime("{$matches['month'][0]} {$matches['start_date'][0]}, $start_year");

    foreach ($matches[0] as $i => $value)
    {
        $year =
            $mindate <= strtotime("{$matches['month'][$i]} {$matches['start_date'][$i]}, $start_year")?
                $start_year : $end_year;

        $matches['end_date'][$i]++;
        $start_time = "{$matches['month'][$i]} {$matches['start_date'][$i]}, $year";
        $end_time = "{$matches['month'][$i]} {$matches['end_date'][$i]}, $year";

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration_in_secs' => 4 * 60 * 60,
            'title' => trim($matches['title'][$i]),
            'host' => $HOST,
            'url' => $URL,
            'timezone' => $TIMEZONE,
            'key' => trim($matches['title'][$i]) . " $year",
            'rid' => $RID
        );
    }
?>
