<!DOCTYPE html>
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <title>Contests list.{if isset($title)}{$title}{/if}</title>
        <meta name="description" content="List of competitions for sports programming.{if isset($description)}{$description}{/if}">
        <link rel="icon" href="/images/favicon.png" type="image/x-icon" />
        <link rel="shortcut icon" href="/images/favicon.png" type="image/x-icon"/>

        <link rel="stylesheet" href="/style.css" type="text/css" />

        <script type="text/javascript" src="https://apis.google.com/js/plusone.js"></script>
        <script type="text/javascript" src="/js/countdown.js"></script>
        <script type="text/javascript" src="/js/yepnope.1.5.4-min.js"></script>
        <script type="text/javascript" src="https://code.jquery.com/jquery-latest.min.js"></script>
{include file="{$smarty.server.DOCUMENT_ROOT}/js/helper.js"}
{include file="{$smarty.server.DOCUMENT_ROOT}/js/google.analytics.js"}

    </head>
    <body>

{if isset($timezone)}
        <script type="text/javascript">
            $(document).ready(function() {
                var current = {$timezone / 60};
                var time = new Date();
                var timezone = -time.getTimezoneOffset();
                if (Math.abs(timezone - current) > 1e-6) {
                    $.ajax({
                        type: "GET",
                        url: "https://{$smarty.server.SERVER_NAME}/",
                        data: "timezone=" + timezone,
                        success: function(data) {
                            if (data == "OK") {
                                location.reload();
                            }
                        }
                    });
                }
            });
        </script>
{/if}

        <div id="fb-root"></div>
{include file="{$smarty.server.DOCUMENT_ROOT}/js/yandex.metrika.js"}

<!--
        <div id="logins">
            <div id="fb-login"><img src="/images/fb-loading.gif"/></div>
        </div>
-->
<!--        <div class='plusone'><div class="g-plusone" data-count="true"></div></div> -->
        <div class="body">
        <div class="container">
        <div class="menu">
            <div class="hidediv">
                <a class="w1">Preferences</a>
                <div>
                    <div class="hidediv">
                        <a>Timezone</a>
                        <div class="left w1 leftalign">
                            <div class="hidediv">
                                <a>Africa</a>
                                <div class="left w2">
                                    <a href='/?timezone=-1:00'>(-1:00) Cape Verde</a>
                                    <a href='/?timezone=+0:00'>(+0:00) Western Sahara Standard</a>
                                    <a href='/?timezone=+1:00'>(+1:00) West Africa, Western Sahara Summer</a>
                                    <a href='/?timezone=+2:00'>(+2:00) Central Africa, South Africa Standard, West Africa Summer</a>
                                    <a href='/?timezone=+3:00'>(+3:00) Eastern Africa</a>
                                    <a href='/?timezone=+4:00'>(+4:00) Mauritius, Reunion, Seychelles</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>Antarctica</a>
                                <div class="left w2">
                                    <a href='/?timezone=+5:00'>(+5:00) Mawson</a>
                                    <a href='/?timezone=+7:00'>(+7:00) Davis</a>
                                    <a href='/?timezone=+8:00'>(+8:00) Casey</a>
                                    <a href='/?timezone=+12:00'>(+12:00) New Zealand Standard</a>
                                    <a href='/?timezone=+13:00'>(+13:00) New Zealand Daylight</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>Asia</a>
                                <div class="left w2">
                                    <a href='/?timezone=+2:00'>(+2:00) Israel Standard</a>
                                    <a href='/?timezone=+3:00'>(+3:00) Arabia Standard, Israel Daylight</a>
                                    <a href='/?timezone=+4:00'>(+4:00) Armenia, Azerbaijan, Georgia Standard, Gulf Standard</a>
                                    <a href='/?timezone=+5:00'>(+5:00) Armenia Summer, Aqtobe, Azerbaijan Summer, Maldives, Pakistan Standard, Tajikistan, Turkmenistan, Uzbekistan,  Yekaterinburg</a>
                                    <a href='/?timezone=+6:00'>(+6:00) Bangladesh Standard, Bhutan, Kyrgyzstan, Novosibirsk, Omsk Standard, Yekaterinburg Summer</a>
                                    <a href='/?timezone=+7:00'>(+7:00) Hovd, Indochina, Krasnoyarsk, Novosibirsk Summer, Omsk Summer, Western Indonesian</a>
                                    <a href='/?timezone=+8:00'>(+8:00) Brunei Darussalam, China Standard, Hong Kong, Irkutsk, Krasnoyarsk Summer, Malaysia, Philippine, Singapore, Ulaanbaatar, Central Indonesian</a>
                                    <a href='/?timezone=+9:00'>(+9:00) Irkutsk Summer, Japan Standard, Korea Standard, East Timor, Eastern Indonesian, Yakutsk</a>
                                    <a href='/?timezone=+10:00'>(+10:00) Vladivostok, Yakutsk Summer</a>
                                    <a href='/?timezone=+11:00'>(+11:00) Magadan, Vladivostok Summer</a>
                                    <a href='/?timezone=+12:00'>(+12:00) Anadyr Summer, Anadyr, Magadan Summer, Kamchatka Summer, Kamchatka</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>Atlantic</a>
                                <div class="left w2">
                                    <a href='/?timezone=-5:00'>(-5:00) Cuba Standard, Eastern Standard</a>
                                    <a href='/?timezone=-4:00'>(-4:00) Atlantic Standard, Cuba Daylight, Eastern Daylight</a>
                                    <a href='/?timezone=-3:00'>(-3:00) Atlantic Daylight</a>
                                    <a href='/?timezone=-1:00'>(-1:00) Azores</a>
                                    <a href='/?timezone=+0:00'>(+0:00) Azores Summer</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>Australia</a>
                                <div class="left w2">
                                    <a href='/?timezone=+7:00'>(+7:00) Christmas Island</a>
                                    <a href='/?timezone=+8:00'>(+8:00) Western Standard</a>
                                    <a href='/?timezone=+9:00'>(+9:00) Western Daylight</a>
                                    <a href='/?timezone=+10:00'>(+10:00) Eastern Standard</a>
                                    <a href='/?timezone=+11:00'>(+11:00) Eastern Daylight, Lord Howe Daylight</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>Europe</a>
                                <div class="left w2">
                                    <a href='/?timezone=+0:00'>(+0:00) Greenwich Mean, Western European</a>
                                    <a href='/?timezone=+1:00'>(+1:00) British Summer, Central European, Irish Standard, Western European Summer</a>
                                    <a href='/?timezone=+2:00'>(+2:00) Central European Summer, Eastern European</a>
                                    <a href='/?timezone=+3:00'>(+3:00) Minsk, Eastern European Summer</a>
                                    <a href='/?timezone=+4:00'>(+4:00) Moscow, Samara</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>America</a>
                                <div class="left w2">
                                    <a href='/?timezone=-9:00'>(-9:00) Alaska Standard</a>
                                    <a href='/?timezone=-8:00'>(-8:00) Alaska Daylight, Pacific Standard</a>
                                    <a href='/?timezone=-7:00'>(-7:00) Mountain Standard, Pacific Daylight</a>
                                    <a href='/?timezone=-6:00'>(-6:00) Central Standard, Mountain Daylight</a>
                                    <a href='/?timezone=-5:00'>(-5:00) Eastern Standard</a>
                                    <a href='/?timezone=-5:00'>(-5:00) Colombia, Ecuador, Peru, Central Daylight, Eastern Standard</a>
                                    <a href='/?timezone=-4:00'>(-4:00) Atlantic Standard, Eastern Daylight, Amazon, Bolivia, Chile Standard, Falkland Island, Guyana, Paraguay</a>
                                    <a href='/?timezone=-3:00'>(-3:00) Atlantic Daylight, West Greenland, Argentina, French Guiana, Paraguay Summer, Suriname, Uruguay</a>
                                    <a href='/?timezone=-2:00'>(-2:00) Western Greenland Summer, Brasilia Summer, Fernando de Noronha, Uruguay Summer</a>
                                    <a href='/?timezone=-1:00'>(-1:00) East Greenland</a>
                                    <a href='/?timezone=+0:00'>(+0:00) Eastern Greenland Summer</a>
                                </div>
                            </div>
                            <div class="hidediv">
                                <a>Pacific</a>
                                <div class="left w2">
                                    <a href='/?timezone=-11:00'>(-11:00) Niue, Samoa Standard, West Samoa</a>
                                    <a href='/?timezone=-10:00'>(-10:00) Cook Island, Tahiti, Tokelau</a>
                                    <a href='/?timezone=-9:00'>(-9:00) Gambier</a>
                                    <a href='/?timezone=-8:00'>(-8:00) Pitcairn Standard</a>
                                    <a href='/?timezone=-6:00'>(-6:00) Easter Island Standard, Galapagos</a>
                                    <a href='/?timezone=-5:00'>(-5:00) Easter Island Summer</a>
                                    <a href='/?timezone=+9:00'>(+9:00) Palau</a>
                                    <a href='/?timezone=+10:00'>(+10:00) Chamorro Standard, Papua New Guinea, Yap</a>
                                    <a href='/?timezone=+11:00'>(+11:00) Eastern Daylight, New Caledonia, Pohnpei Standard, Solomon IslandsTime, Vanuatu</a>
                                    <a href='/?timezone=+12:00'>(+12:00) Fiji, Gilbert Island, Marshall Islands, New Zealand Standard, Tuvalu, Wallis and Futuna</a>
                                    <a href='/?timezone=+13:00'>(+13:00) Fiji Summer, New Zealand Daylight, Phoenix Island</a>
                                    <a href='/?timezone=+14:00'>(+14:00) Line Islands</a>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="hidediv">
                        <a class="w1">Duration</a>
                        <div class="left w1">
{$durationlimitselect}
                        </div>
                    </div>
                    <div class="hidediv">
                        <a class="w1">Viewmode</a>
                        <div class="left w1">
{$viewmode}
                        </div>
                    </div>
                    <div class="hidediv">
                        <a class="w1">Tabs</a>
                        <div class="left w1">
                            <a href='?tabs=new'>New</a>
                            <a href='?tabs=current'>Current</a>
                        </div>
                    </div>
                    <div class="hidediv">
                        <a class="w1">Hide resources</a>
                        <div class="left">
{$hideresources}
                        </div>
                    </div>
                </div>
            </div>

        </div>
        </div>

        <div class="mainbox">
{if isset($list)}
{$list}
{elseif isset($calendar)}
{$calendar}
{/if}
        </div>
        </div>

<!-- Yandex.Metrika informer -->{literal}
        <div class='informer'>
<a href="http://metrika.yandex.ru/stat/?id=9707797&amp;from=informer"
target="_blank" rel="nofollow"><img src="//bs.yandex.ru/informer/9707797/1_0_FFFFFFFF_FFFFFFFF_0_uniques"
style="width:80px; height:15px; border:0;" alt="Яндекс.Метрика" title="Яндекс.Метрика: данные за сегодня (уникальные посетители)" onclick="try{Ya.Metrika.informer({i:this,id:9707797,type:0,lang:'ru'});return false}catch(e){}"/></a>
        </div>
{/literal}<!-- /Yandex.Metrika informer -->

        {*<a href='http://validator.w3.org/check?uri=referer'><span class='hidden'>HTML5</span></a><br>*}
        {*<a href='http://jigsaw.w3.org/css-validator/check/referer?profile=css3'><span class='hidden'>CSS</span></a><br>*}

        <div id="author">
            <a href="https://plus.google.com/100014771119535019566?prsrc=3" rel="author" style="text-decoration:none;"><img src="https://ssl.gstatic.com/images/icons/gplus-32.png" alt="" style="border:0;width:32px;height:32px;"/></a>            <a rel="author" href="https://plus.google.com/100014771119535019566"></a>
<!--
            <a rel="author" href="https://plus.google.com/100014771119535019566">
              <img src="http://www.google.com/images/icons/ui/gprofile_button-16.png" width="16" height="16">
            </a>
-->
        </div>
{include file="{$smarty.server.DOCUMENT_ROOT}/js/block.share.js"}

{include file="{$smarty.server.DOCUMENT_ROOT}/js/afterload.js"}
{include file="{$smarty.server.DOCUMENT_ROOT}/js/reformal.js"}
    </body>
</html>
