<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $keys = array();
    $parse_full_list = isset($_GET['parse_full_list']);
    foreach (array('', '2012', '2013', '2014', '2015', '2016', '2017', '2018', '2019', '2020') as $season) {
        foreach (array('', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12') as $suffix) {
            if (!$season && $suffix) {
                continue;
            }

            $web_archive_time = $season . $suffix;

            if ($parse_full_list) {
                echo ",$web_archive_time";
            } else if ($web_archive_time) {
                return;
            }

            if ($web_archive_time) {
                $url = "https://web.archive.org/web/$web_archive_time/http://russianaicup.ru/";
            } else {
                $url = $URL;
            }
            $page = curlexec($url);

            if (!preg_match("#<title>[^<]*-\s*([^<]*)</title>#", $page, $match)) {
                continue;
            }
            list($title, $year) = explode(" ", $match[1], 2);

            preg_match_all("#<strong>(?P<title>[^<]*)</strong>:\s*(?P<start_time>[^.;<]*)#xi", $page, $matches, PREG_SET_ORDER);

            if (!$web_archive_time && preg_match('#<h[^>]*class="[^"]*alignRight[^"]*"[^>]*>(?<title>[^:]*)(?P<desc>[^<]*)#', $page, $match)
                && !preg_match('#(freeze|заморож)#', $match['desc'])
            ) {
                $rtitle = $match['title'];
                $rdesc = $match['desc'];
                preg_match('#secondsBefore\s*=\s*(?<before>[0-9]+)#', $page, $match);
                $rtime = time() + intval($match['before']);
                $rtime = intval(round($rtime / 3600) * 3600);
            }

            $normalize_time = function($time, $year) {
                $time = trim($time) . ' ' . $year;
                $time = replace_russian_moths_to_number($time);
                $month = date('m', strtotime($time));
                if ($month < 4) {
                    $time = preg_replace_callback("#(\d+)$#", function($m) { return $m[1] + 1; }, $time);
                }
                return $time;
            };


            $sandbox_idx = -1;
            $idx = 0;
            foreach ($matches as $match)
            {
                $round = $match['title'];

                $round = str_replace('Раунд', 'Round', $round);
                $round = str_replace('Песочница', 'Sandbox', $round);
                $round = str_replace('Финал', 'Finals', $round);

                $key = $title . '. ' . $round;
                if (isset($keys[$key])) {
                    if ($web_archive_time) {
                        $contests[$keys[$key]]['info']['parse']['web_archive_time'] = $web_archive_time;
                        $contests[$keys[$key]]['info']['parse']['web_archive_url'] = $url;
                    }
                    continue;
                }

                $start_time = trim($match['start_time']);
                $start_time = preg_replace('#\s(to|по|till|до)\s#', ' – ', $start_time);
                $start_time = preg_replace('#–#', '-', $start_time);

                if (preg_match('#(?:from|с)((?:\s+(?:-\s*)?(?:[^0-9\s,-]+\s*[0-9]+|[[0-9]+\s*[^0-9\s,-]+)(?:,\s*[0-9:]+\s*UTC)?)+)#', $start_time, $match)) {
                    $start_time = trim($match[1]);
                }

                if (preg_match('#[0-9]+\s*-\s*[0-9]+#', $start_time)) {
                    $end_time = preg_replace('#[0-9]+\s*-\s*([0-9]+)#', '\1', $start_time);
                    $start_time = preg_replace('#([0-9]+)\s*-\s*[0-9]+#', '\1', $start_time);
                    $duration = 2880;
                } else if (preg_match('#([^-]+)-([^-]+)#', $start_time, $match)) {
                    $start_time = $match[1];
                    $end_time = $match[2];
                    unset($duration);
                } else {
                    $duration = 0;
                    $end_time = $start_time;
                }

                if (empty($start_time) || substr_count($start_time, " ") > 5) {
                    continue;
                }

                $start_time = $normalize_time($start_time, $year);
                $end_time = $normalize_time($end_time, $year);

                if (isset($rtitle) && $round == $rtitle) {
                    if (strpos($rdesc, 'before end') !== false) {
                        $end_time = $rtime;
                        unset($duration);
                    } else if (strpos($rdesc, 'before start') !== false) {
                        $start_time = $rtime;
                    }
                }

                if ($round == "Sandbox" && isset($duration)) {
                    $sandbox_idx = count($contests);
                } else if ($sandbox_idx !== -1) {
                    $contests[$sandbox_idx]['end_time'] = $end_time;
                }
                $idx += 1;


                $contest = array(
                    'start_time' => $start_time,
                    'title' => $title . '. ' . $round,
                    'url' => $HOST_URL,
                    'host' => $HOST,
                    'key' => $key,
                    'rid' => $RID,
                    'standings_url' => url_merge($HOST_URL, "/contest/$idx/standings"),
                    'timezone' => $TIMEZONE
                );
                if ($web_archive_time) {
                    $contest['info'] = array('parse' => array(
                        'web_archive_time' => $web_archive_time,
                        'web_archive_url' => $url,
                    ));
                }

                $keys[$key] = count($contests);

                if (isset($duration)) {
                    $contest['duration'] = $duration;
                } else {
                    $contest['end_time'] = $end_time;
                }

                $contests[] = $contest;
            }
        }
    }
?>
