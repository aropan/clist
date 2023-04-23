<?php
    if (!function_exists('http_parse_headers')) {
        function http_parse_headers($raw_headers) {
            $headers = [];

            foreach (explode("\n", $raw_headers) as $i => $h) {
                if (strpos($h, ": ") === false) {
                    continue;
                }
                list($key, $value) = explode(': ', $h, 2);

                $value = trim($value);
                if (isset($headers[$key])) {
                    if (!is_array($headers[$key])) {
                        $headers[$key] = array($headers[$key]);
                    }
                    array_push($headers[$key], $value);
                } else {
                    $headers[$key] = $value;
                }
            }
            return $headers;
        }
    }

    function starts_with($haystack, $needle)
    {
        return substr($haystack, 0, strlen($needle)) == $needle;
    }

    function microtime_float()
    {
        list($usec, $sec) = explode(" ", microtime());
        return ((float)$usec + (float)$sec);
    }

    function hex2str($hex)
    {
        $r = '';
        for ($i = 0; $i < strlen($hex) - 1; $i += 2)
            $r .= chr(hexdec($hex[$i] . $hex[$i + 1]));
        echo $r . "<p>\n";
        return $r;
    }

    function unicode_decode($str)
    {
        return preg_replace("#(?:\\%|\\\\)u([0-9A-Fa-f]{4})#ie", "iconv('utf-16', 'utf-8//TRANSLIT', hex2str('$1'))", $str);
    }

    $PREV_TIME = microtime_float();
    $NLOGMSG = 0;

    function crop_logmsg() {
        $all_lines = file(LOGFILE);
        $lines = array_slice($all_lines , -COUNTLINEINLOGFILE);
        file_put_contents(LOGFILE, implode('', $lines));
    }

    function logmsg($msg = '')
    {
        global $PREV_TIME;
        global $NLOGMSG;

        $curr_time = microtime_float();
        $msg = date('d.m  H:i:s   ', intval($curr_time)) . sprintf("+%-7.2lf-  ", $curr_time - $PREV_TIME) . $msg . "\n";

        $fp = fopen(LOGFILE, 'a');
        fwrite($fp, $msg);
        fclose($fp);

        if ($NLOGMSG == 0) {
            register_shutdown_function('crop_logmsg');
        } else if ($NLOGMSG >= COUNTLINEINLOGFILE) {
            crop_logmsg();
            $NLOGMSG = 0;
        }

        $PREV_TIME = $curr_time;
        $NLOGMSG += 1;
    }


    $cookiefile = dirname(__FILE__) . '/cookie.file';
    if (file_exists($cookiefile) && filesize($cookiefile) > 4 * 1024 * 1024) {
        @unlink($cookiefile);
    }

    function filter_cookies($cookiefile) {
        $cookies = file_get_contents($cookiefile);
        $cookies = explode("\n", $cookies);
        $cookies = array_reverse($cookies);
        $filtered = array();
        $counters = array();
        foreach ($cookies as $cookie) {
            if (empty($cookie)) {
                continue;
            }
            if (substr_count($cookie, "\t") == 6) {
                $tokens = explode("\t", $cookie);
                $domain = $tokens[0];
                if (!isset($counters[$domain])) {
                    $counters[$domain] = 0;
                }
                if (++$counters[$domain] > 50) {
                    continue;
                }
            }
            $filtered[] = $cookie;
        }
        $filtered = array_reverse($filtered);
        $cookies = implode("\n", $filtered) . "\n";
        file_put_contents($cookiefile, $cookies);
    }

    if (ISCLI) {
        filter_cookies($cookiefile);
    }

    $CID = curl_init();
    $USER_AGENT = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:43.0) Gecko/20100101 Firefox/43.0";
    curl_setopt($CID, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($CID, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($CID, CURLOPT_AUTOREFERER, true);
    curl_setopt($CID, CURLOPT_TIMEOUT, 15);
    curl_setopt($CID, CURLOPT_USERAGENT, $USER_AGENT);
    curl_setopt($CID, CURLOPT_COOKIEJAR, $cookiefile);
    curl_setopt($CID, CURLOPT_COOKIEFILE, $cookiefile);
    curl_setopt($CID, CURLOPT_SSL_VERIFYPEER, false);
    curl_setopt($CID, CURLOPT_ENCODING, "gzip");
    curl_setopt($CID, CURLINFO_HEADER_OUT, true);
    curl_setopt($CID, CURLOPT_VERBOSE, true);


    $COOKIE = array();

    function redirect_url($url) {
        stream_context_set_default(array(
            'http' => array(
                'method' => 'HEAD'
            )
        ));
        $headers = get_headers($url, true);
        if ($headers !== false && isset($headers['Location'])) {
            if (is_array($headers['Location'])) {
                return end($headers['Location']);
            }
            return $headers['Location'];
        }
        return $url;
    }

    function curlexec(&$url, $postfields = NULL, $params = array())
    {
        global $CID;
        global $COOKIE;
        $prev_url = curl_getinfo($CID, CURLINFO_EFFECTIVE_URL);
        if (!parse_url($url, PHP_URL_HOST) && isset($prev_url) && $prev_url) {
            $url = url_merge($prev_url, $url);
        }

        if (DEBUG) {
            echo "url = $url\n";
        }

        // echo "curl_setopt(CURLOPT_URL, $url)\n";
        empty($url) && die("Empty URL on " . __FILE__ . ":" . __LINE__);
        curl_setopt($CID, CURLOPT_URL, $url);

        $header = array('Accept-Language: en;q=0.8, ru;q=0.2');
        if (isset($params["http_header"])) {
            $header = array_merge($header, $params["http_header"]);
        }
        curl_setopt($CID, CURLOPT_HTTPHEADER, $header);

        if (isset($params["no_header"])) {
            curl_setopt($CID, CURLOPT_HEADER, false);
        } else {
            curl_setopt($CID, CURLOPT_HEADER, true);
        }

        $cachefile = CACHEDIR . "/" . parse_url($url, PHP_URL_HOST) . "-" . md5(preg_replace("#/?timeMin=[^&]*#", "", $url)) . ".html";
        if ($postfields !== NULL)
        {
            curl_setopt($CID, CURLOPT_POST, true);
            curl_setopt($CID, CURLOPT_POSTFIELDS, $postfields);
        } else {
            curl_setopt($CID, CURLOPT_POST, false);
        }

        if (CACHE && $postfields === NULL && file_exists($cachefile))
        {
            $page = file_get_contents($cachefile);
        }
        else
        {
            $page = curl_exec($CID);
            if (preg_match('#charset=["\']?([-a-z0-9]+)#i', $page, $match))
            {
                $charset = $match[1];
                if (!preg_match('#^utf.*8$#i', $charset))
                {
                    if (mb_check_encoding($page, $charset))
                    {
                        $converted = iconv($charset, 'utf8//TRANSLIT', $page);
                        if ($converted != false) {
                            $page = $converted;
                        }
                    }
                }
            }
            if (CACHE) {
                file_put_contents($cachefile, $page);
                if (substr(sprintf("%o", fileperms($cachefile)), -4) != "0766") {
                    chmod($cachefile, 0766);
                }
            }
        }
        if (!isset($params["no_logmsg"])) {
            logmsg("URL: " . (CACHE? "[cached] " : "") . "`$url`");
        }
        if (curl_errno($CID)) {
            logmsg('ERROR ' . curl_errno($CID) . ': ' . curl_error($CID));
        }

        $sep = strrpos($page, "\r\n\r\n");
        $header = substr($page, 0, $sep);
        $header = http_parse_headers($header);

        $header_ = array();
        foreach ($header as $k => $v) {
            $header_[strtolower($k)] = $v;
        }
        $header = $header_;

        if (isset($params["json_output"])) {
            $json_decode_page = json_decode(substr($page, $sep + 4), true);
            if ($json_decode_page !== null) {
                $page = $json_decode_page;
            }
        }

        if (isset($header['set-cookie'])) {
            $a = $header['set-cookie'];
            $a = is_array($a)? $a : array($a);
            foreach ($a as $c) {
                $kv = explode(";", $c, 2)[0];
                list($k, $v) = explode("=", $kv, 2);
                $COOKIE[$k] = $v;
            }
        }
        $url = curl_getinfo($CID, CURLINFO_EFFECTIVE_URL);
        return $page;
    }

    function response_code() {
        global $CID;
        return curl_getinfo($CID, CURLINFO_RESPONSE_CODE);
    }

    function HSVtoRGB(array $hsv) {
        list($H,$S,$V) = $hsv;
        //1
        $H *= 6;
        //2
        $I = floor($H);
        $F = $H - $I;
        //3
        $M = $V * (1 - $S);
        $N = $V * (1 - $S * $F);
        $K = $V * (1 - $S * (1 - $F));
        //4
        switch ($I) {
            case 0:
                list($R,$G,$B) = array($V,$K,$M);
                break;
            case 1:
                list($R,$G,$B) = array($N,$V,$M);
                break;
            case 2:
                list($R,$G,$B) = array($M,$V,$K);
                break;
            case 3:
                list($R,$G,$B) = array($M,$N,$V);
                break;
            case 4:
                list($R,$G,$B) = array($K,$M,$V);
                break;
            case 5:
            case 6: //for when $H=1 is given
                list($R,$G,$B) = array($V,$M,$N);
                break;
        }
        return array((int)($R * 255), (int)($G * 255), (int)($B * 255));
    }

    $atimezone = array(
       "Pacific/Honolulu" => "Гавайи",
       "America/Anchorage" => "Аляска",
       "America/Los_Angeles" => "Североамериканское тихоокеанское время",
       "America/Denver" => "Горное время, Мексика",
       "America/Chicago" => "Центральное время, Центральноамериканское время, Мексика",
       "America/New_York" => "Североамериканское восточное время, Южноамериканское тихоокеанское время",
       "America/Caracas" => "Каракас",
       "America/Halifax" => "Атлантическое время",
       "America/St_Johns" => "Ньюфаундленд",
       "America/Argentina/Buenos_Aires" => "Южноамериканское восточное время, Гренландия",
       "America/Sao_Paulo" => "Среднеатлантическое время",
       "Atlantic/Azores" => "Азорские острова, Кабо-Верде",
       "Etc/GMT" => "Западноевропейское время",
       "Europe/Belgrade" => "Центральноевропейское время  Западное центральноафриканское время",
       "Africa/Cairo" => "Восточноевропейское время, Египет, Израиль, Ливан, Ливия, Турция, ЮАР",
       "Europe/Kaliningrad" => "Калининградское время, Восточноафриканское время",
       "Asia/Tehran" => "Тегеранское время",
       "Europe/Moscow" => "Московское время",
       "Asia/Kabul" => "Афганистан",
       "Asia/Tashkent" => "Западный Казахстан, Пакистан, Таджикистан, Туркменистан, Узбекистан",
       "Asia/Calcutta" => "Индия, Шри-Ланка",
       "Asia/Katmandu" => "Непал",
       "Asia/Yekaterinburg" => "Екатеринбургское время, центральная и восточная части Казахстана",
       "Indian/Cocos" => "Мьянма",
       "Asia/Omsk" => "Омское время, Новосибирск, Кемерово, Юго-Восточная Азия",
       "Asia/Shanghai" => "Красноярское время, Западноавстралийское время",
       "Asia/Irkutsk" => "Иркутское время, Корея, Япония",
       "Australia/Darwin" => "Центральноавстралийское время",
       "Asia/Yakutsk" => "Якутское время, Восточноавстралийское время, Западно-тихоокеанское время",
       "Asia/Vladivostok" => "Владивостокское время, Центрально-тихоокеанское время",
       "Asia/Magadan" => "Магаданское время, Маршалловы Острова, Фиджи, Новая Зеландия",
       "Pacific/Tongatapu" => "Самоа, Тонга",
       "Pacific/Kiritimati" => "Острова Лайн"
    );

    foreach ($atimezone as $timezone => $value)
    {
        $dtimezone =
            timezone_offset_get(
                new DateTimeZone($timezone),
                new DateTime("now", new DateTimeZone("GMT"))
            );

        $dtime = ($dtimezone >= 0? '+' : '-') . sprintf("%02d:%02d", abs((int)$dtimezone) / 3600, abs((int)$dtimezone) % 3600 / 60);
        $atimezone[$timezone] = array(
            'text' => "($dtime) $value",
            'value' => $dtimezone
        );
    }
    foreach (DateTimeZone::listIdentifiers() as $timezone)
    {
        $dtimezone =
            timezone_offset_get(
                new DateTimeZone($timezone),
                new DateTime("now", new DateTimeZone("GMT"))
            );
        $dtime = ($dtimezone >= 0? '+' : '-') . sprintf("%02d:%02d", abs((int)$dtimezone) / 3600, abs((int)$dtimezone) % 3600 / 60);
        $was = False;
        foreach ($atimezone as $t) {
            if ($t['value'] == $dtimezone) {
                $was = True;
                break;
            }
        }
        if (!$was) {
            $atimezone[$timezone] = array(
                'text' => "($dtime) $timezone",
                'value' => $dtimezone
            );
        }
    }

    $adurationlimit = array (
        "3 hours" => 3 * 60 * 60,
        "6 hours" => 6 * 60 * 60,
        "12 hours" => 12 * 60 * 60,
        "1 day" => 24 * 60 * 60,
        "3 days" => 3 * 24 * 60 * 60,
        "8 days" => 8 * 24 * 60 * 60,
        "21 days" => 21 * 24 * 60 * 60,
        "no limit" => 3000 * 365 * 24 * 60 * 60
    );


    function cmp_timezone($a, $b)
    {
        if ($a['value'] == $b['value']) return 0;
        return (int)$a['value'] < (int)$b['value']? -1 : 1;
    }
    uasort($atimezone, 'cmp_timezone');

    function replace_russian_moths_to_number($page)
    {
        $page = preg_replace(
            array('#\sянваря\s#','#\sфевраля\s#','#\sмарта\s#','#\sапреля\s#','#\sмая\s#','#\sиюня\s#','#\sиюля\s#','#\sавгуста\s#','#\sсентября\s#','#\sоктября\s#','#\sноября\s#','#\sдекабря\s#'),
            array('.01.','.02.','.03.','.04.','.05.','.06.','.07.','.08.','.09.','.10.','.11.','.12.'),
            $page
        );
        $page = preg_replace(
            array('#\sянваря#','#\sфевраля#','#\sмарта#','#\sапреля#','#\sмая#','#\sиюня#','#\sиюля#','#\sавгуста#','#\sсентября#','#\sоктября#','#\sноября#','#\sдекабря#'),
            array('.01','.02','.03','.04','.05','.06','.07','.08','.09','.10','.11','.12'),
            $page
        );
        $page = preg_replace(
            array('#\sянв#','#\sфев#','#\sмар#','#\sапр#','#\sмай#','#\sмая#','#\sиюн#','#\sиюл#','#\sавг#','#\sсен#','#\sокт#','#\sноя#','#\sдек#'),
            array('.01','.02','.03','.04','.05','.05','.06','.07','.08','.09','.10','.11','.12'),
            $page
        );
        return $page;
    }

    function get_calendar_authorization()
    {
        if (!file_exists(CALENDARCREDENTIALSFILE))
        {
            return false;
        }
        $credentials = json_decode(file_get_contents(CALENDARCREDENTIALSFILE), true);
        $token = $credentials["token_response"];
        return "{$token['token_type']} {$token['access_token']}";
    }

    function get_xpath_from_string($page)
    {
        $dom = new DomDocument();
        $error_reporting = ini_get('error_reporting');
        ini_set('error_reporting', E_ERROR);
        $dom->loadHTML($page);
        ini_set('error_reporting', $error_reporting);
        $xpath = new DomXPath($dom);
        return $xpath;
    }

    function unparse_url($parsed_url)
    {
        $scheme   = isset($parsed_url['scheme']) ? $parsed_url['scheme'] . '://' : '';
        $host     = isset($parsed_url['host']) ? $parsed_url['host'] : '';
        $port     = isset($parsed_url['port']) ? ':' . $parsed_url['port'] : '';
        $user     = isset($parsed_url['user']) ? $parsed_url['user'] : '';
        $pass     = isset($parsed_url['pass']) ? ':' . $parsed_url['pass']  : '';
        $pass     = ($user || $pass) ? "$pass@" : '';
        $path     = isset($parsed_url['path']) ? $parsed_url['path'] : '';
        $query    = isset($parsed_url['query']) ? '?' . $parsed_url['query'] : '';
        $fragment = isset($parsed_url['fragment']) ? '#' . $parsed_url['fragment'] : '';
        return "$scheme$user$pass$host$port$path$query$fragment";
    }

    function url_merge($original, $new, $clear_query = false)
    {
        if (is_string($original)) {
            $original = parse_url($original);
        }
        if (is_string($new)) {
            $new = parse_url($new);
        }
        $qs = null;
        if (!empty($original['query']) && is_string($original['query'])) {
            parse_str($original['query'], $original['query']);
        }
        if (!empty($new['query']) && is_string($new['query'])) {
            parse_str($new['query'], $new['query']);
        }
        if (isset($original['query']) || isset($new['query'])) {
            if (!isset($original['query'])) {
                $qs = $new['query'];
            } elseif (!isset($new['query'])) {
                $qs = $original['query'];
            } else {
                $qs = array_merge($original['query'], $new['query']);
            }
        }
        if (isset($original['path']) && isset($new['path']) && $new['path'][0] != '/') {
            $path = preg_replace('#[^/]+$#', '', $original['path']);
            $new['path'] = $path . $new['path'];
        }
        $result = array_merge($original, $new);
        if ($clear_query) {
            unset($result['query']);
        } else {
            $result['query'] = $qs;
        }
        foreach ($result as $k => $v) {
            if ($v === null) {
                unset($result[$k]);
            }
        }
        if (!empty($result['query'])) {
            $result['query'] = http_build_query($result['query']);
        }
        if ($result['path'][0] != '/') {
            $result['path'] = "/{$result['path']}";
        }
        return unparse_url($result);
    }

    function romanic_number($integer, $upcase = true)
    {
        $table = array(
            'M' => 1000,
            'CM' => 900,
            'D' => 500,
            'CD' => 400,
            'C' => 100,
            'XC' => 90,
            'L' => 50,
            'XL' => 40,
            'X' => 10,
            'IX' => 9,
            'V' => 5,
            'IV' => 4,
            'I' => 1
        );
        $return = '';
        while($integer > 0)
        {
            foreach($table as $rom=>$arb)
            {
                if($integer >= $arb)
                {
                    $integer -= $arb;
                    $return .= $rom;
                    break;
                }
            }
        }
        return $return;
    }

    function ending_ordinal($integer)
    {
        switch ($integer % 10) {
            case 1: return "st";
            case 2: return "nd";
            case 3: return "rd";
            default: return "th";
        }
    }

    // https://gist.github.com/erickpatrick/3039081#file-seconds-human-redable-text-php-L9
    function human_readable_seconds($secs)
    {
        $units = array(
            "week"   => 7 * 24 * 3600,
            "day"    =>     24 * 3600,
            "hour"   =>          3600,
            "minute" =>            60,
            "second" =>             1,
        );
        // specifically handle zero
        if ($secs < 1) {
            return number_format($secs, 3) . " seconds";
        }
        $s = "";
        foreach ( $units as $name => $divisor ) {
            if ($quot = intval($secs / $divisor)) {
                $s .= "$quot $name";
                $s .= (abs($quot) > 1 ? "s" : "") . ", ";
                $secs -= $quot * $divisor;
            }
        }
        return substr($s, 0, -2);
    }


    // https://stackoverflow.com/questions/2955251/php-function-to-make-slug-url-string/2955878#2955878
    function slugify($text)
    {
        // cyrillic characters into latin letters
        $text = transliterator_transliterate('Russian-Latin/BGN', $text);

        // replace non letter or digits by -
        $text = preg_replace('~[^\pL\d]+~u', '-', $text);

        // transliterate
        $text = iconv('utf-8', 'us-ascii//TRANSLIT', $text);

        // remove unwanted characters
        $text = preg_replace('~[^-\w]+~', '', $text);

        // trim
        $text = trim($text, '-');

        // remove duplicate -
        $text = preg_replace('~-+~', '-', $text);

        // lowercase
        $text = strtolower($text);

        return $text;
    }

    function short_message($data) {
        if (is_array($data)) {
            $data = json_encode($data);
        }
        $lines = preg_split("/[\n\r]+/", $data);
        $line = trim($lines[0]);
        $line = mb_strimwidth($line, 0, 75, '...');
        return $line;
    }
?>
