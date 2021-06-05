<?php
    require_once dirname(__FILE__) . "/../../config.php";

    function get_algorithm_key(&$title) {
        $title = preg_replace('#single\s*round\s*match#i', 'SRM', $title);
        $title = preg_replace('#marathon\s*match#i', 'MM', $title);
        if (preg_match('#\s+(test|testing)$#i', $title)) {
            return false;
        }
        if (!preg_match('#(?P<key>(?:(?:rookie\s*)?srm|mm)\s*[-/.0-9]*[0-9]|TCO[0-9]+.*(?:algorithm|marathon)?\s*round\s*([.0-9a-z]*[0-9a-z])?)#i', $title, $match)) {
            return false;
        }
        return $match['key'];
    }

    function normalize_title($title, $date) {
        $ret = strtolower($title);
        $ret = preg_replace('/[0-9]*([0-9]{2})\s*tco(\s+)/', 'tco\1\2', $ret);
        $ret = preg_replace('/tco\s*[0-9]*([0-9]{2})(\s+)/', 'tco\1\2', $ret);
        return $ret;
    }

    $debug_ = $RID == -1 || DEBUG;

    $_DATE_FORMAT = 'm.d.Y';

    $url_scheme_host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);

    $authorization = get_calendar_authorization();
    $calendar_parsed = false;
    if ($authorization) {
        $calendar = "appirio.com_bhga3musitat85mhdrng9035jg@group.calendar.google.com";
        $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar) . "/events?timeMin=" . urlencode(date("c", time() - 7 * 24 * 60 * 60));
        if ($debug_) {
            echo "url = $url\n";
        }
        $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
        if (!isset($data["items"])) {
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
            if ($debug_) {
                echo "url = $url\n";
            }
            $json = curlexec($url, null, array("json_output" => 1));
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
                    $key = get_algorithm_key($title);
                    if (!$key) {
                        if (!isset($c['technologies']) || !in_array("Data Science", array_values($c['technologies']))) {
                            continue;
                        }
                        $key = "challenge=" . $c['id'];
                    }

                    $_contests[] = array(
                        "start_time" => $c["registrationStartDate"],
                        "end_time" => $c["submissionEndDate"],
                        "standings_url" => "https://www.topcoder.com/challenges/" . $c['id'] . "?tab=submissions",
                        "title" => $c["name"],
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
                                $w1 = explode(" ", normalize_title($c["title"], $date));
                                $w2 = explode(" ", normalize_title($ro["title"], $date));
                                $intersect = count(array_intersect($w1, $w2));
                                $iou = $intersect / count(array_unique(array_merge($w1, $w2)));
                                if ($intersect == count($w2)) {
                                    $iou = 0.9 + $iou * 0.1;
                                }
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
                if ($date < $now - 5 * 24 * 60 * 60 || $now - 1 * 24 * 60 * 60 < $date) {
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
