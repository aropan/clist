<?php
    function resolveDocumentRoot() {
        $current_script = isset($_SERVER['SCRIPT_NAME'])? dirname($_SERVER['SCRIPT_NAME']) : '';
        $current_path   = dirname($_SERVER['SCRIPT_FILENAME']);

        /* work out how many folders we are away from document_root
           by working out how many folders deep we are from the url.
           this isn't fool proof */
        $adjust = explode("/", $current_script);
        $adjust = count($adjust)-1;

        /* move up the path with ../ */
        $traverse = str_repeat("../", $adjust);
        $adjusted_path = sprintf("%s/%s", $current_path, $traverse);

        /* real path expands the ../'s to the correct folder names */
        return realpath($adjusted_path);
    }

    if (!isset($_SERVER['DOCUMENT_ROOT']))
        $_SERVER['DOCUMENT_ROOT'] = resolveDocumentRoot();

    require_once "config.php";

    if (isset($_GET['timezone']) && !isset($atimezone[$_GET['timezone']]))
    {
        $timezone = $_GET['timezone'];
        unset($_GET['timezone']);
        if (preg_match("#^[- ]?[0-9]{1,4}$#", $timezone))
        {
            $tz_return = true;
            $tz = $timezone * 60;
        }

        if (preg_match("#^[- ]?[0-9]{1,2}:[0-9]{1,2}$#", $timezone))
        {
            $h = $m = 0;
            sscanf($timezone, '%d:%d', $h, $m);
            if ($h < 0) $m = -$m;
            $tz = $h * 3600 + $m * 60;
        }

        if (isset($tz)) {
            foreach ($atimezone as $key => $value)
            {
                if ($value['value'] == $tz)
                {
                    $_GET['timezone'] = $key;
                    break;
                }
            }
        }
    }

    if (isset($_GET['durationlimit']) && array_search($_GET['durationlimit'], $adurationlimit) === false)
    {
        $durationlimit = $_GET['durationlimit'];
        unset($_GET['durationlimit']);

        if (preg_match("/\s*(\d+|no)\s*(\w+)\s*/i", $durationlimit, $match))
        {
            $match = $match[1] . ' ' . $match[2];
            if (isset($adurationlimit[$match]))
                $_GET['durationlimit'] = $adurationlimit[$match];
        }

        if (preg_match("/\s*(\d+)\s*/i", $durationlimit, $match))
        {
            $match = $match[1];
            if (array_search($match, $adurationlimit))
                $_GET['durationlimit'] = $match;
        }
    }

    foreach ($_POST as $key => $value)
    {
        $_GET[$key] = $value;
    }

    foreach (array('timezone', 'durationlimit', 'view', 'mode', 'tabs') as $key)
    {
        if (isset($_GET[$key])) setcookie($key, $_GET[$key], time() + 365 * 24 * 60 * 60, '/'); else
        if (isset($_COOKIE[$key])) setcookie($key, $_COOKIE[$key], time() + 365 * 24 * 60 * 60, '/');
    }

    if (isset($tz_return) && $tz_return)
    {
        if (!isset($_GET["timezone"])) {
            echo "FAIL";
        } else {
            echo "OK";
        }
        return;
    }

    if (isset($_GET['action']))
    {
        switch ($_GET['action'])
        {
            case 'resources':
                if (!isset($_GET['arid'])) $_GET['arid'] = array(-1);
                setcookie("arid", serialize($_GET['arid']), time() + 365 * 24 * 60 * 60);
            break;
        }
        header("Request-URI: /");
        header("Content-Location: /");
        header("Location: /");
    }

    $timezone = isset($_GET['timezone']) && isset($atimezone[$_GET['timezone']])?
        $_GET['timezone'] :
            (isset($_COOKIE['timezone']) && isset($atimezone[$_COOKIE['timezone']])?
                $_COOKIE['timezone'] : "Europe/Kaliningrad");

    $durationlimit = isset($_GET['durationlimit']) && array_search($_GET['durationlimit'], $adurationlimit) !== false?
        $_GET['durationlimit'] :
            (isset($_COOKIE['durationlimit']) && array_search($_COOKIE['durationlimit'], $adurationlimit) !== false?
                $_COOKIE['durationlimit'] : end($adurationlimit));
//    echo $durationlimit;

    $view = isset($_GET['view'])? $_GET['view'] : (isset($_COOKIE['view'])? $_COOKIE['view'] : "list");
    $mode = isset($_GET['mode'])? $_GET['mode'] : (isset($_COOKIE['mode'])? $_COOKIE['mode'] : "normal");
    $arid = isset($_GET['arid'])? $_GET['arid'] : (isset($_COOKIE['arid'])? unserialize(stripslashes($_COOKIE['arid'])) : array());
    $tabs = isset($_GET['tabs'])? $_GET['tabs'] : (isset($_COOKIE['tabs'])? $_COOKIE['tabs'] : "current");

//    echo strlen(stripslashes($_COOKIE['arid']));
//    die(strlen($_COOKIE['arid']));

    if (isset($_GET['byhosts'])) {
        $hosts = explode(",", $_GET['byhosts']);
        //$hosts = array_map('mysql_real_escape_string', $hosts);
        $hosts = $db->escapeArray($hosts);
        $hosts = "'" . implode("', '", $hosts) . "'";
        $arid = $db->select("clist_resource", "id", "host not in ($hosts)");
        $arid = array_map(create_function('$r', 'return $r["id"];'), $arid);
    }

    if ($arid === false || count($arid) == 0) $arid = array(-1);

    $dtimezone = $atimezone[$timezone]['value'];
/*
    $timezoneselect = "<select id='timezone' onchange='selectOnChange(this)'>\n";
    foreach ($atimezone as $key => $value)
        $timezoneselect .= "\t<option " . ($key == $timezone? 'selected ' : '') . "value='$key' data-time='{$value['value']}'>{$value['text']}</option>\n";
    $timezoneselect .= "</select>\n";
//*/
    $durationlimitselect = "";
    foreach ($adurationlimit as $title => $value)
        $durationlimitselect .= "\t\t\t\t<a href='?durationlimit=" . urlencode($title) . "'>$title</a>\n";

    $viewmodeselect = "";
    foreach (array('Calendar' => 'calendar', 'List' => 'list') as $title => $value)
        $viewmodeselect .= "\t\t\t\t<a href='?view=". urlencode($value) . "'>$title</a>\n";

    $resources = $db->getArray("select host, id, uid from clist_resource");
    function cmp_resource($a, $b) { if ($a['host'] == $b['host']) return 0; return $a['host'] < $b['host']? -1 : 1; }
    uasort($resources, 'cmp_resource');

    $hideresources = "<form method='POST'><table class='hidden'>\n";
    $i = 0;
    $k = 2;
    foreach ($resources as $resource)
    {
        $url = $view == 'calendar'?
            "https://www.google.com/calendar/ical/" . urlencode($resource['uid']) . "/public/basic.ics" :
            "http://{$resource['host']}";

        if ($i % $k == 0) $hideresources .= "\t<tr>\n";
        $hideresources .= "\t\t<td><input type='checkbox' name='arid[]' value='{$resource['id']}'" . (array_search($resource['id'], $arid) !== false? ' checked=""' : '') . "><a href='$url' target='{$resource['host']}'>{$resource['host']}</a></td>\n";
        $i++;
        if ($i % $k == 0) $hideresources .= "\t</tr>\n";
    }
    if ($i % $k)
    {
        for (; $i % $k; $i++) $hideresources .= "\t\t<td></td>\n";
        $hideresources .= "\t</tr>\n";
    }

    $hideresources .= "\t<tr>\n";
    $hideresources .= "\t\t<td colspan='$k' class='centeralign'>\n";
    $hideresources .= "\t\t<input type='hidden' name='action' value='resources'/>\n";
    $hideresources .= "\t\t<input type='submit' value='choose'>\n";
    $hideresources .= "\t\t</td>\n";
    $hideresources .= "\t</tr>\n";
    $hideresources .= "</table></form>\n";

    $_GET['type'] = isset($_GET['type'])? $_GET['type'] : '';
    switch ($_GET['type'])
    {
        case 'bsuir-training':
            $arid = array(-1);
            foreach ($db->getArray("SELECT id FROM clist_resource WHERE NOT id IN (1,2,3,6,7,12,13,24,25)") as $i)
                $arid[] = $i['id'];
        break;
    }
    $where = "not clist_contest.resource_id in (" . implode(',', $arid) . ")";

    $resources = $db->getArray("SELECT host FROM clist_resource WHERE  NOT id IN (" . implode(',', $arid) .  ") ORDER BY host");
    $desc_header = "";
//    $desc_header = " " . $atimezone[$timezone]['text'] . ".";
    $a = array();
    foreach ($resources as $resource)
    {
        $a[] = $resource['host'];
        $data['resources'][] = $resource['host'];
    }

    if (count($a))
    {
        shuffle($a);
        $desc_header .= " " . implode(', ', $a) . ".";
    }

    $title_header = "";
    switch ($_GET['type'])
    {
        case 'bsuir-training': $title_header .= ' BSUIR Training.'; break;
    }

    switch ($view)
    {
        case 'calendar':
            $src = "https://www.google.com/calendar/embed?title=+&amp;wkst=2&amp;hl=en&amp;bgcolor=%23FFFFFF";

            $resources = $db->getArray("SELECT * FROM clist_resource WHERE uid <> '' AND NOT id IN (" . implode(',', $arid) .  ") ORDER BY host");

            //if (count($resources) > 50)
            //{
                //$src .= "&amp;src=" . urlencode("clist.x10.mx@gmail.com");
            //}
            //else
            {
                foreach ($resources as $i => $resource)
                {
                    $src .= "&amp;src=" . urlencode($resource['uid']);
                    // $src .= "&amp;src=" . urlencode($resource['uid']) . "&amp;color=" . urlencode($resource['color']);
                }
            }
            $calendar = "
                <div id='calendar'>
                    <iframe id='calendarframe' frameborder='no' scrolling='no' height='800px' width='100%' src='$src&amp;ctz=$timezone'></iframe>
                </div>";
            $smarty->assign('calendar', $calendar);
        break;

        default:
            $time = date('Y-m-d H:i:s', time());
            $time_day_before = date('Y-m-d H:i:s', time() - 1 * 24 * 60 * 60);


            if ($view == 'rss')
            {
                $time_week_before = date('Y-m-d H:i:s', time() - 7 * 24 * 60 * 60);
                $contests =  $db->getArray("select * from clist_contest where $where and (end_time > '$time') and (created > '$time_week_before') order by created desc, title");
            }
            else
            {
                switch ($mode)
                {
                    case 'latestadded':
                        $contests =  $db->getArray("select * from clist_contest where $where and (end_time > '$time') order by created desc, title");
                    break;

                    default:
                        $coming_contests = $db->getArray("select * from clist_contest where $where and (start_time > '$time') order by start_time, title");
                        $past_running_contests = $db->getArray("select * from clist_contest where $where and (end_time > '$time_day_before' and start_time <= '$time') order by end_time, title");
                        if (count($coming_contests))
                            $contests = array_merge($past_running_contests, array_combine(range(count($past_running_contests), count($past_running_contests) + count($coming_contests) - 1), $coming_contests));
                        else
                            $contests = $past_running_contests;
                    break;
                }
            }


            $table = "<table class='contests'>\n";
            $table .= "\t<tr class='header'>\n";
            foreach (array("Time", "Duration", "Time left", "Event") as $s)
                $table .= "\t\t<td>$s</td>\n";
            $table .= "\t</tr>\n";

            $count_running = $count_pending = 0;

//            foreach ($contests as $i => $contest)
//                $contests[$i]['insert_time'] = round(strtotime($contests[$i]['insert_time']) / (24 * 60 * 60));

            $desc_contests = array();
            foreach ($contests as $i => $contest)
            {
                $data_contest = array();

                $duration = strtotime($contest['end_time']) - strtotime($contest['start_time']);
                if ($duration > $durationlimit) continue;

                $dduration = (int)($duration / (24 * 60 * 60));
                $hduration = (int)($duration / (60 * 60));
                $mduration = (int)($duration % (60 * 60) / 60);

        //        if ($dduration && ($hduration + $mduration))
        //            $duration = sprintf("%d days<br>%02d:%02d", $dduration, $hduration, $mduration); else
                if ($dduration > 1)
                    $duration = sprintf("%d days", (int)(($duration + 17280) / (24 * 60 * 60)));
                else
                    $duration = sprintf("%02d:%02d", $hduration, $mduration);

                $title = $contest['title'];

                $start_time = strtotime($contest['start_time']) + $dtimezone;
                $end_time = strtotime($contest['end_time']) + $dtimezone;


                if ($dduration == 0)
                {
                    $url_start_time =
                    $url_end_time =
                        'http://www.timeanddate.com/worldclock/fixedtime.html?msg=' . urlencode($title) . '&iso=' . date('Ymd\THi', strtotime($contest['start_time'])) . "&ah=$hduration&am=$mduration";
                }
                else
                {
                    $url_start_time = 'http://www.timeanddate.com/worldclock/fixedtime.html?msg=' . urlencode('Start "' . $title . '"') . '&iso=' . date('Ymd\THi', strtotime($contest['start_time']));
                    $url_end_time = 'http://www.timeanddate.com/worldclock/fixedtime.html?msg=' . urlencode('End "' . $title . '"') . '&iso=' . date('Ymd\THi', strtotime($contest['end_time']));
                }


//                $start_time = "<a href='" . htmlspecialchars($url_start_time) . "' rel='nofollow' target='_blank' class='timezone' data-time='" . date('r', strtotime($contest['start_time'])) . "'>$start_time</a>";
//                $end_time = "<a href='" . htmlspecialchars($url_end_time) . "' rel='nofollow' target='_blank' class='timezone' data-time='" . date('r', strtotime($contest['end_time'])) . "'>$end_time</a>";
//                s = 'Ymd';

                if (date('Ymd', $start_time) == date('Ymd', $end_time))
                {
                    $data_contest['date']['value'] = date('d.m.Y', $end_time);
                    $time = "\n\t\t\t<div>" . date('d.m.Y D', $end_time) . "</div>\n" .
                        "\t\t\t<div>\n\t\t\t\t<a href='" . htmlspecialchars($url_start_time) . "' rel='nofollow' target='_blank' class='timezone' data-time='" . date('r', strtotime($contest['start_time'])) . "'>" . date('H:i', $start_time) . "</a> - \n" .
                        "\t\t\t\t<a href='" . htmlspecialchars($url_end_time) . "' rel='nofollow' target='_blank' class='timezone' data-time='" . date('r', strtotime($contest['end_time'])) . "'>" . date('H:i', $end_time) . "</a>\n\t\t\t</div>\n";
                }
                else
                {
                    $time =
                        "\n\t\t\t<div class='topTime'><a href='" . htmlspecialchars($url_start_time) . "' rel='nofollow' target='_blank' class='timezone' data-time='" . date('r', strtotime($contest['start_time'])) . "'>" . date('d.m.y D H:i', $start_time) . "</a></div>\n" .
                        "\t\t\t<div class='bottomTime'><a href='" . htmlspecialchars($url_end_time) . "' rel='nofollow' target='_blank' class='timezone' data-time='" . date('r', strtotime($contest['end_time'])) . "'>" . date('d.m.y D H:i', $end_time) . "</a></div>\n";
                }
                $time .=
                    "\t\t\t<meta itemprop='startDate' content='" . date('c', strtotime($contest['start_time'])) . "'/>\n".
                    "\t\t\t<meta itemprop='endDate' content='" . date('c', strtotime($contest['end_time'])) . "'/>\n\t\t";

                $time_left = ($contest['start_time'] <= date('Y-m-d H:i:s', time()))? $contest['end_time'] : $contest['start_time'];
                $time_left = strtotime($time_left) - time();
                $time_left *= 1000;

                $resource = $contest['host'];
                $resource = "<a itemprop='location' href='" . htmlspecialchars("http://$resource") . "'". ($tabs == 'new'? " target='_blank'" : "") . ">$resource</a>";

                $title = "<a itemprop='url' href='" . htmlspecialchars($contest['url']) . "'" . ($tabs == 'new'? " target='_blank'" : "") . "><span itemprop='summary'>" . htmlspecialchars($contest['title']) . "</span></a><a href='#' class='alarm'></a>";
                $title .= "<div class='resource'>$resource</div>";

                if ($contest['end_time'] < date('Y-m-d H:i:s', time()))
                    $state = 'over';
                else
                {
                    if ($contest['start_time'] <= date('Y-m-d H:i:s', time()))
                        $state = 'running';
                    else
                        $state = 'pending';
                    if (count($desc_contests) < 10)
                        $desc_contests[] = str_replace('"', "'", $contest['title']);
                }

                $count_running += $state == 'running';
                $count_pending += $state == 'pending';

                $table .= "\t<tr itemscope itemtype='http://data-vocabulary.org/Event' class='contest " . ($i % 2? "odd" : "even") . " $state'>\n";
                $table .= "\t\t<td class='datetime'>$time</td>\n";
//                $table .= "\t<td class='datetime'>$end_time</td>\n";
                $table .= "\t\t<td class='duration'>$duration</td>\n";

                if ($contest['end_time'] < date('Y-m-d H:i:s', time()))
                    $table .= "\t\t<td>over</td>\n";
                else
                    $table .= "\t\t<td class='countdown' data-time='" . $time_left . "'></td>\n";

//                $table .= "\t<td class='resource'>$resource</td>\n";

                $table .= "\t\t<td class='title'>$title</td>\n";
                $table .= "\t</tr>\n";

                $data_contest['date']['start'] = array('time' => date('d.m.y H:i', $start_time), 'url' => $url_start_time);
                $data_contest['date']['end'] = array('time' => date('d.m.y H:i', $end_time), 'url' => $url_end_time);
                $data_contest['date']['timeLeft'] = $time_left;
                $data_contest['title'] = $contest['title'];
                $data_contest['url'] = $contest['url'];
                $data_contest['resource'] = $contest['host'];
                $data_contest['status'] = $state;
                $data_contest['guid'] = md5($contest['key']);
                $data_contest['duration'] = $duration;

                $data['contests'][] = $data_contest;
            }

            $table .= "\t<tr class='footer'><td colspan='4'></td></tr>\n";
            $table .= "</table>\n";

            if ($count_running || $count_pending)
            {
                $title_header .=
                    ' [' .
                    ($count_running? "$count_running running" : '') .
                    ($count_running && $count_pending? ', ' : '') .
                    ($count_pending? "$count_pending pending" : '') .
                    ']';
            }

            if (count($desc_contests))
            {
                shuffle($desc_contests);
                $desc_header .= " " . implode(', ', $desc_contests) . ".";
            }

            $smarty->assign('list', $table);
    }

    $time = date('H:i:s', time() + $dtimezone);
    $title_header .= " ($time, " . sprintf("%s%02d:%02d", $dtimezone < 0? "-" : "+", abs($dtimezone) / 3600, abs($dtimezone) % 3600 / 60) . ")";

    $smarty->assign('durationlimitselect', $durationlimitselect);
    $smarty->assign('hideresources', $hideresources);
    $smarty->assign('viewmode', $viewmodeselect);
    $smarty->assign('title', $title_header);
    $smarty->assign('description', $desc_header);
    if (!isset($_GET['timezone'])) {
        $smarty->assign('timezone', $dtimezone);
    }
    if (isset($data)) {
        $smarty->assign('data', $data);
    }

    switch ($view)
    {
        case 'rss':
//            print_r($data);
            $smarty->caching = 1;
            $smarty->display('rss.xml');
            break;

        default:
            $smarty->display('index.tpl');
    }
?>
