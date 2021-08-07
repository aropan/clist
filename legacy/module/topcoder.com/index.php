<?php
    require_once dirname(__FILE__) . "/../../config.php";

    function choose_unique($parts, &$title) {
        if (count($parts) != 2) {
            return;
        }
        list($fs, $sc) = $parts;

        $fs = explode(" ", $fs);
        $sc = explode(" ", $sc);

        if (count($fs) < count($sc)) {
            list($fs, $sc) = array($sc, $fs);
            $result = $parts[1];
        } else {
            $result = $parts[0];
        }

        $idx = 0;
        for ($idx = 0, $i = 0; $i < count($fs) && $idx < count($sc); ++$i) {
            if ($fs[$i] == $sc[$idx]) {
                $idx += 1;
            }
        }
        if ($idx == count($sc)) {
            $title = $result;
        }
    }

    function get_algorithm_key(&$title) {
        $parts = preg_split('#\s+-\s+#', $title);
        choose_unique($parts, $title);
        $title = preg_replace('#\bsingle\s*round\s*match\b#i', 'SRM', $title);
        $title = preg_replace('#\btopcoder\s*open\b#i', 'TCO', $title);
        $title = preg_replace('#\btopcoder\s*collegiate\s*challenge\b#i', 'TCCC', $title);
        $title = preg_replace('#^mm\b#i', 'Marathon Match', $title);
        $title = preg_replace('#([0-9])-([0-9])#', '\1\2', $title);
        $title = preg_replace('#\s*-\s*#', ' ', $title);
        $title = trim($title);
        if (preg_match('#\b(test|testing|practice)\b$#i', $title)) {
            return false;
        }
        if (!preg_match('#(?P<key>(?:(?:rookie\s*|beginner\s*)?srm|^marathon\s*match)\s*[-/.0-9]*[0-9]|^(?:[0-9]+\s?TCO|TCO\s?[0-9]+).*(?:algorithm|marathon)?\s*\b(?:match|round)\b\s*([.0-9a-z]*[0-9a-z])?)#i', $title, $match)) {
            return false;
        }
        return $match['key'];
    }

    function normalize_title($title, $date) {
        $ret = strtolower($title);
        $ret = preg_replace('/\b(algorithm|round|marathon|match)\b/', ' ', $ret);
        $ret = preg_replace('/[0-9]*([0-9]{2})\s*tco(\s+)/', 'tco\1\2', $ret);
        $ret = preg_replace('/tco\s*[0-9]*([0-9]{2})(\s+)/', 'tco\1\2', $ret);
        $ret = preg_replace('/^[0-9]{2}([0-9]{2})(\s+)/', 'tco\1\2', $ret);
        $ret = preg_replace('/ +/', ' ', $ret);
        return $ret;
    }

    $debug_ = $RID == -1 || DEBUG;

    $_DATE_FORMAT = 'm.d.Y';

    $url_scheme_host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);

    $authorization = get_calendar_authorization();
    $calendar_parsed = false;
    if ($authorization) {
        $url = 'https://www.topcoder.com/community/events';
        $page = curlexec($url);

        if (preg_match('#src="[^"]*calendar.google.com[^"]*embed[^"]*src=(?P<calendar>[^"&]*)#', $page, $match)) {
            $calendar = urldecode($match['calendar']);
            $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar) . "/events?timeMin=" . urlencode(date("c", time() - 7 * 24 * 60 * 60));
            if ($debug_) {
                echo "url = $url\n";
            }
            $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
        } else {
            $calendar = false;
        }

        if (!$calendar) {
            trigger_error("Not found calendar in $url", E_USER_WARNING);
        } else if (!isset($data["items"])) {
            echo $data['error']['message'] . "\n";
        } else {
            $calendar_parsed = true;
            if ($debug_) {
                echo "Total items: " . count($data["items"]) . "\n";
            }
            foreach ($data["items"] as $item)
            {
                if ($item["status"] != "confirmed" || !isset($item["summary"])) {
                    continue;
                }

                $title = $item["summary"];
                if (strpos($title, "Registration") !== false) {
                    continue;
                }

                $key = get_algorithm_key($title);
                if (!$key) {
                    continue;
                }

                $url = $URL;
                foreach (array("description", "location") as $field) {
                    if (!isset($item[$field])) {
                        continue;
                    }
                    if (preg_match('#(?P<href>https?://[^\s"]*(?:MatchDetails|ViewProblemStatement)[^\s"]*)#', $item[$field], $match)) {
                        $url = $match["href"];
                        break;
                    }
                }

                $start = $item["start"][isset($item["start"]["dateTime"])? "dateTime" : "date"];
                $end = $item["end"][isset($item["end"]["dateTime"])? "dateTime" : "date"];
                $date = date($_DATE_FORMAT, strtotime($start));
                if (!isset($item["id"])) {
                    trigger_error("No set id for event $title", E_USER_WARNING);
                }
                $contest = array(
                    "start_time" => $start,
                    "end_time" => $end,
                    "title" => $title,
                    "url" => $url,
                    "key" => $key,
                    "_calendar" => true
                );
                $_contests[] = $contest;
            }
        }
    }

    $limit = 50;
    $ids = array();
    foreach (array(
        array("filter" => "status=ACTIVE"),
        array("filter" => "status=COMPLETED"),
        array("filter" => "status=ACTIVE", "filter[tracks][data_science]" => "true"),
        array("filter" => "status=COMPLETED", "filter[tracks][data_science]" => "true"),
    ) as $params) {
        for ($offset = 0; ; $offset += $limit) {
            $params["offset"] = $offset;
            $params["limit"] = $limit;
            $query = http_build_query($params);
            $url = "https://api.topcoder.com/v4/challenges/?" . $query;
            for ($attempt = 0; $attempt < 5; ++$attempt) {
                $json = curlexec($url, null, array("json_output" => 1));
                if (isset($json["result"]) && isset($json["result"]['content'])) {
                    break;
                }
                sleep(10);
            }
            if (isset($json["result"]) && isset($json["result"]['content'])) {
                $stop = false;
                foreach ($json["result"]['content'] as $c) {
                    $ok = true;
                    foreach (array("name", "id", "registrationStartDate", "submissionEndDate") as $f) {
                        if (!isset($c[$f])) {
                            $ok = false;
                            break;
                        }
                    }

                    if (!$ok) {
                        continue;
                    }

                    if (isset($ids[$c['id']])) {
                        continue;
                    }
                    $ids[$c['id']] = true;

                    $title = $c["name"];
                    $track = $c['track'];
                    $sub_track = $c['subTrack'];
                    if ($track == 'DEVELOP') {
                        if ($sub_track != 'DEVELOP_MARATHON_MATCH') {
                            continue;
                        }
                    } else if ($track == 'DATA_SCIENCE') {
                        if ($sub_track != 'MARATHON_MATCH') {
                            continue;
                        }
                    } else {
                        continue;
                    }
                    $key = get_algorithm_key($title);
                    if (!$key || strpos($key, 'SRM') !== false) {
                        $key = "challenge=" . $c['id'];
                    }
                    $_contests[] = array(
                        "start_time" => $c["registrationStartDate"],
                        "end_time" => $c["submissionEndDate"],
                        "standings_url" => "https://www.topcoder.com/challenges/" . $c['id'] . "?tab=submissions",
                        "title" => $title,
                        "url" => $url_scheme_host . "/challenges/" . $c['id'],
                        "key" => $key,
                    );
                }
                if (!count($json["result"]["content"]) || $stop) {
                    break;
                }
                if (!isset($_GET['parse_full_list']) && $params['filter'] == 'status=COMPLETED') {
                    break;
                }
            } else {
                trigger_error("Incorrect json response", E_USER_WARNING);
                break;
            }
        }
    }

    $_ = array();
    foreach ($_contests as $v) {
        $v['title'] = trim($v['title']);
        $v['title'] = preg_replace('/ {2,}/', ' ', $v['title']);
        $start_time = strtotime($v['start_time']);

        $ok = true;
        foreach ($_ as $c) {
            if (strpos($c['title'], $v['title']) !== false && strtotime($c['start_time']) == $start_time && $c['url'] == $v['url']) {
                $ok = false;
                break;
            }
        }

        if ($ok) {
            $_[] = $v;
        }
    }
    $_contests = $_;
    unset($_);

    if ($calendar_parsed) {
        $add_from_stats = isset($_GET['parse_full_list']);
        $iou_treshhold = 0.61803398875;

        $round_overview = array();
        foreach (array('https://www.topcoder.com/tc?module=MatchList') as $base_url) {
            $nr = 200;
            $sr = 1;
            for (;;) {
                $url = $base_url . "&nr=$nr&sr=$sr";
                if ($debug_) {
                    echo $url . "\n";
                }
                $page = curlexec($url);
                if (!preg_match_all('#(?:<td[^>]*>(?:[^<]*<a[^>]*href="(?P<url>[^"]*/stat[^"]*rd=(?P<rd>[0-9]+)[^"]*)"[^>]*>(?P<title>[^<]*)</a>[^<]*|(?P<date>[0-9]+\.[0-9]+\.[0-9]+))</td>[^<]*){2}#', $page, $matches, PREG_SET_ORDER)) {
                    return;
                }
                foreach ($matches as $match) {
                    $key = get_algorithm_key($match['title']);
                    $ro = array(
                        'url' => url_merge($base_url, htmlspecialchars_decode($match['url'])),
                        'title' => $match['title'],
                        'date' => $match['date'],
                        'key' => $key? $key : $match['title'],
                    );
                    $round_overview[$match['rd']] = $ro;
                }
                if (!$add_from_stats) {
                    break;
                }
                if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>next#', $page, $match)) {
                    break;
                }
                $sr += $nr;
            }
        }

        for ($iter = 0; $iter < 2; ++$iter) {
            foreach ($_contests as $i => $c) {
                $ret = preg_match('/&rd=(?P<rd>[0-9]+)/', $c['url'], $match);
                if ($ret != ($iter == 0)) {
                    continue;
                }
                if ($ret) {
                    $rd = $match['rd'];
                    if (!isset($round_overview[$rd])) {
                        continue;
                    }
                } else {
                    if (!isset($c['_calendar'])) {
                        continue;
                    }
                    $opt = $iou_treshhold;
                    $t = null;
                    foreach (array(0, -1, 1) as $shift_day) {
                        $date = date('m.d.Y', strtotime($c['start_time']) + $shift_day * 24 * 60 * 60);
                        foreach ($round_overview as $k => $ro) {
                            if ($ro['date'] == $date) {
                                $a1 = explode(" ", normalize_title($c["title"], $date));
                                $a2 = explode(" ", normalize_title($ro["title"], $date));
                                $intersection = 0;
                                foreach ($a1 as $w1) {
                                    foreach ($a2 as $w2) {
                                        if (is_numeric($w1) || is_numeric($w2)) {
                                            if ($w1 == $w2) {
                                                $intersection += 1;
                                                break;
                                            }
                                        } else if (substr($w1, 0, strlen($w2)) == $w2 || substr($w2, 0, strlen($w1)) == $w1) {
                                            $intersection += 1;
                                            break;
                                        }
                                    }
                                }
                                $union = count($a1) + count($a2) - $intersection;
                                $iou = $intersection / $union;
                                if ($iou > $opt) {
                                    $opt = $iou;
                                    $t = $k;
                                }
                            }
                        }
                    }
                    if ($t === null) {
                        continue;
                    }
                    if ($debug_) {
                        echo $c['title'] . " <-> " . $round_overview[$t]['title'] . "\n";
                    }
                    $rd = $t;
                }
                $_contests[$i]['standings_url'] = $round_overview[$rd]['url'];
                if (isset($_contests[$i]['key'])) {
                    $_contests[$i]['old_key'] = $_contests[$i]['key'];
                }
                $_contests[$i]['key'] = $round_overview[$rd]['key'];
                unset($round_overview[$rd]);
            }
        }

        foreach ($round_overview as $ro) {
            $ds = explode('.', $ro['date']);
            list($ds[0], $ds[1]) = array($ds[1], $ds[0]);
            $date_str = implode('.', $ds);
            if (!$add_from_stats) {
                $now = time();
                $date = strtotime($date_str);
                if ($date < $now - 5 * 24 * 60 * 60) {
                    continue;
                }
            }

            # FIX same name
            if (abs(strtotime($date_str) - strtotime('06.03.2006')) < 4 * 24 * 60 * 60 && strpos($ro['title'], 'TCO06 Sponsor') === 0) {
                $ro['title'] .= ' Track Round';
            }

            $title = $ro['title'];
            $key = get_algorithm_key($title);
            if (!$key) {
                $key = $title;
            }

            $_contests[] = array(
                "start_time" => $date_str,
                "end_time" => $date_str,
                "title" => $title,
                "url" => $ro['url'],
                "key" => $key,
                "standings_url" => $ro['url'],
            );
        }
    }

    foreach ($_contests as $c) {
        unset($c['_calendar']);
        $c["host"] = $HOST;
        $c["rid"] = $RID;
        $c["timezone"] = "UTC";
        $contests[] = $c;
    }

    if ($RID === -1) {
        echo "Total contests: " . count($_contests) . "\n";
    }
?>
