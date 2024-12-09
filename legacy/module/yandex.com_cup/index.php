<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'https://contest.yandex.com/yacup/schedule';
    $page = curlexec($url);

    preg_match_all('#<h1[^>]*>(?P<name>[^<]*)</h1>\s*(?P<table><table[^>]*>.*?</table>)#s', $page, $matches, PREG_SET_ORDER);

    foreach ($matches as $category) {
        $stages = parsed_table($category['table']);

        foreach ($stages as $stage) {
            $start_time = $stage['start-time'];
            $start_time = preg_replace('#[\(\)]#', '', $start_time);

            $end_time = $stage['end-time'];
            $end_time = preg_replace('#[\(\)]#', '', $end_time);

            $duration = $stage['duration'];
            $duration = preg_replace('#\s*\(.*?\)$#', '', $duration);

            $stage_name = $stage['stage'];
            $stage_name = preg_replace('#\s+-\s+.*$#', '', $stage_name);

            $year = date('Y', strtotime($start_time));
            $month = date('n', strtotime($start_time));
            if ($month >= 9) {
                $season = ($year + 0) . "-" . ($year + 1);
            } else {
                $season = ($year - 1) . "-" . ($year + 0);
            }

            $subcategories = array(false);
            if ($year == 2024 && $category['name'] == 'Mobile development' && $stage_name == 'Final round') {
                $subcategories = array('iOS', 'Android');
            }

            foreach ($subcategories as $subcategory) {
                $name = $category['name'];
                if ($subcategory) {
                    $name .= " $subcategory";
                }
                $title = "$name. $stage_name";
                $key = slugify($name) . ' ' . slugify($stage_name) . ' ' . $season;
                $contests[] = array(
                    'start_time' => $start_time,
                    'end_time' => $end_time,
                    'duration' => $duration,
                    'title' => $title,
                    'url' => $url,
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $key,
                );
            }
        }
    }

    // $url = $URL;

    // $page = curlexec($url);
    // $year = date('Y');

    // preg_match_all('#<a[^>]*home-hero__link[^>]*home-hero__link_(?P<type>[a-z]+)[^>]*href="(?P<href>[^"]*)"[^>]*>.*?<[^>]*home-hero__title[^>]*>(?P<name>[^<]*)(<[^>/]*>[^<]*)*(</[^>]*>\s*)*</a>#', $page, $matches, PREG_SET_ORDER);

    // foreach ($matches as $category) {
    //     $url = url_merge($URL, $category['href']);
    //     $page = curlexec($url);

    //     preg_match_all('#<[^>]*home-stages__date[^>]*>(?<date>[^<]*)(?:<em>(?P<tag>[^<]*)</em>)?<[^>]*>\s*<[^>]*home-stages__title[^>]*>(?<title>[^<]*)<[^>]*>#', $page, $matches, PREG_SET_ORDER);
    //     foreach ($matches as $stage) {
    //         $title = $category['name'] . '. ' . $stage['title'];

    //         $sep = '–';
    //         $start_time = trim($stage['date']);
    //         if (empty($start_time)) {
    //             continue;
    //         }
    //         $start_time = preg_replace("#[^0-9a-z$sep]+#i", " ", $start_time);
    //         $start_time = preg_replace("#\s*$sep\s*#i", $sep, $start_time);
    //         $end_time = null;
    //         if (strpos($start_time, $sep) !== false) {
    //             list($start_time, $end_time) = explode($sep, $start_time);
    //             $start_time = trim($start_time);
    //             $end_time = trim($end_time);
    //             if (preg_match('#^[0-9]+$#', $end_time)) {
    //                 $end_time = preg_replace('#[0-9]+#', $end_time, $start_time);
    //             }
    //         }
    //         if (strpos($start_time, $year) === false) {
    //             $start_time .= " $year";
    //         }
    //         $start_time = '12:00 ' . $start_time;

    //         if ($end_time) {
    //             if (strpos($end_time, $year) === false) {
    //                 $end_time .= " $year";
    //             }
    //             $end_time = strtotime($end_time) + 24 * 60 * 60;
    //         }

    //         $month = date('n', strtotime($start_time));
    //         if ($month >= 9) {
    //             $season = ($year + 0) . "-" . ($year + 1);
    //         } else {
    //             $season = ($year - 1) . "-" . ($year + 0);
    //         }

    //         $duration = 0;
    //         if (preg_match('#algorithm#i', $category['name'])) {
    //             if (preg_match('#marathon#i', $stage['title'])) {
    //                 $duration = 7 * 24 * 60;  // 7 days
    //             } else if (preg_match('#sprint#i', $stage['title'])) {
    //                 $duration = 120;  // 120 minutes
    //             } else if (preg_match('#final#i', $stage['title'])) {
    //                 $duration = 120;
    //             }
    //         } else if (preg_match('#back-?end#i', $category['name'])) {
    //             $duration = 300;
    //         } else if (preg_match('#front-?end#i', $category['name'])) {
    //             $duration = 300;
    //         } else if (preg_match('#analytics#i', $category['name'])) {
    //             $duration = 180;
    //         } else if (preg_match('#mobile#i', $category['name'])) {
    //             if (preg_match('#qualifying#i', $stage['title'])) {
    //                 $duration = 120;
    //             }
    //         } else if (preg_match('#juniors#i', $category['name'])) {
    //             $duration = 120;
    //         }

    //         $key = $category['type'] . ' ' . strtolower($stage['title']) . ' ' . $season;

    //         $contests[] = array(
    //             'start_time' => $start_time,
    //             'end_time' => $end_time,
    //             'duration' => $duration,
    //             'title' => $title,
    //             'url' => $url,
    //             'host' => $HOST,
    //             'rid' => $RID,
    //             'timezone' => $TIMEZONE,
    //             'key' => $key,
    //         );
    //     }
    // }
?>
