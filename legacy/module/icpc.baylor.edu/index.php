<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    if (!preg_match('#src="(?P<js>/static/js/main.[^"]*.js)"#', $page, $match)) {
        trigger_error('Not found main.js', E_USER_WARNING);
        return;
    }

    $page = curlexec($match['js']);
    if (!preg_match('#XWIKI:"(?P<xwiki>[^"]*)"#', $page, $match)) {
        trigger_error('Not found xwiki', E_USER_WARNING);
        return;
    }
    $xwiki = url_merge($URL, '/' . trim($match['xwiki'], '/'));
    $url = "$xwiki/virtpublic/worldfinals/schedule";

    $page = curlexec($url);

    if (!preg_match("#>The (?P<year>[0-9]{4}) (?P<title>(?:ACM-)?ICPC World Finals)#i", $page, $match)) {
        trigger_error('Not found year and title', E_USER_WARNING);
        return;
    }

    $year = $match['year'];
    $title = $match['title'];

    if (!preg_match("#>hosted by(?:[^,<]*,)?\s*(?P<where>[^<]*?)\s*<#i", $page, $match)) {
        trigger_error('Not found where', E_USER_WARNING);
        return;
    }
    $title .= ". " . $match["where"];

    if (!preg_match("#held on (?P<date>[^,\.<]*)#", $page, $match)) {
        trigger_error('Not found date', E_USER_WARNING);
        return;
    }

    $start_time = $match['date'] . ' ' . $year;

    $contests[] = array(
        'start_time' => $start_time,
        'duration' => '24 hours',
        'duration_in_secs' => 5 * 60 * 60,
        'title' => $title,
        'url' => $URL,
        'host' => $HOST,
        'key' => $year,
        'rid' => $RID,
        'timezone' => $TIMEZONE
    );

    $parse_full_list = isset($_GET['parse_full_list']);
    for (;$year > 1970;) {
        --$year;
        $path = "/community/history-icpc-$year";

        $url = "$xwiki/$path";
        $page = curlexec($url);
        $url = url_merge($URL, $path);

        if (strpos($page, "page not found") !== false) {
            break;
        }

        if (preg_match("#[A-Z][a-z]* [0-9]+(?:-[0-9]+)?, $year#", $page, $match)) {
            $page = str_replace($match[0], '', $page);
            $time = preg_replace('#-[0-9]+#', '', $match[0]);
        } else {
            $time = "02.01.$year";
        }

        if (preg_match_all("#[Tt]he(?P<title>(?:\s+[A-Z0-9][A-Za-z0-9]*)+)#", $page, $matches)) {
            $title = "";
            foreach ($matches['title'] as $t) {
                if (strlen($t) > strlen($title)) {
                    $title = $t;
                }
            }
            if (strpos($title, "World Champions") !== false) {
                $title = "The " . ($year - 1976) . "th Annual ACM ICPC World Finals";
            } else {
                $title = preg_replace('#International Collegiate Programming Contest#i', 'ICPC', $title);
            }
        } else {
            $title = "World Finals";
        }
        if (preg_match("# in\s*(?:<[^>]*>\s*)?(?P<name>[A-Z][A-Za-z.]+(?:,?\s*[A-Z][A-Za-z.]+)*)#", $page, $match)) {
            $title .= ". " . trim($match['name'], '.');
        }

        $contests[] = array(
            'start_time' => $time,
            'duration' => '24 hours',
            'duration_in_secs' => 5 * 60 * 60,
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'key' => $year,
            'rid' => $RID,
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
