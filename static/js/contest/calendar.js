function filterCallbackCalendar(value) {
    calendar.refetchEvents()
}

$(function() {
    function get_calendar_height() {
        return $(window).height() - ($('#calendar').closest('.tab-content').position().top + 20)
    }

    $(window).resize(function() {
        calendar.setOption('height', get_calendar_height())
    });

    calendar = new FullCalendar.Calendar($('#calendar')[0], {
        plugins: ['dayGrid', 'timeGrid', 'list', 'moment', 'momentTimezone'],
        nowIndicator: true,
        customButtons: customButtonDesc,
        header: {
            left: 'title',
            right: customButtonGroup + ' today,dayGridMonth,timeGridWeek,listWeek prev,next'
        },
        titleFormat: '{MMMM {D}}, YYYY',
        firstDay: 1,
        timezone: timezone,
        events: function (fetchInfo, successCallback, failureCallback) {
            $.ajax({
                url: '/get/events/',
                type: 'POST',
                traditional: true,
                data: {
                    start: fetchInfo.startStr,
                    end: fetchInfo.endStr,
                    categories: ['calendar'],
                    party: $('#party-name').attr('data-slug'),
                    search_query: $('#filter [type="text"]').val(),
                    ignore_filters:
                        $('.ignore-filter')
                        .filter(function () { return $(this).attr('data-value') == '1' })
                        .map(function () { return $(this).attr('data-id') })
                        .toArray(),
                },
                success: function (response) {
                    successCallback(response)
                },
                error: function(response) {
                    log_ajax_error(response)
                    failureCallback({message: 'there was an error while fetching events!'})
                }
            });
        },
        eventRender: function (info) {
            var event = info.event
            var element = info.el
            var start = FullCalendarMoment.toMoment(event.start, calendar)
            var end = FullCalendarMoment.toMoment(event.end, calendar)
            var now = FullCalendarMoment.toMoment($.now(), calendar)
            var countdown = event.extendedProps.countdown
            var start_time = start.format('YYYY-MM-DD HH:mm')
            var end_time = event.end? end.format('YYYY-MM-DD HH:mm') : null;
            var title =
                    event.title
                    + '<div>' + event.extendedProps.host + '</div>'
                    + '<div>Duration: ' + event.extendedProps.hr_duration + '</div>'
                    + '<div>Start: ' + start_time + '</div>'
                    + (event.end? '<div>End: ' + end_time + '</div>' : '')
                    + (countdown?
                        '<div class="countdown">'
                        + (start < now? "Ends in " : "Starts in ")
                        + '<span class="countdown-timestamp hidden">'  + countdown + '</span>'
                        + '<span class="countdown-format">' + getFormatTime(countdown) + '</span>'
                        + '</div>' : '')
            $(element).tooltip({
                title: title,
                placement: 'top',
                container: 'body',
                html: true,
                delay: {
                    'show': 300,
                    'hide': 100,
                },
                trigger: 'hover',
            })
            $(element).on('inserted.bs.tooltip', function() {
                $('.countdown-format').each(function(idx, val) {
                    var countdown = parseInt($(val).parent().find('.countdown-timestamp').html())
                    $(val).html(getFormatTime(countdown - ($.now() - page_load) / 1000))
                })
            })
            var icon = $('<img src="/imagefit/static_resize/32x32/' + event.extendedProps.icon + '" height="14" width="14">&nbsp;</img>')
            icon.prependTo(element.querySelector('.fc-content'))
            if (contest_toggle) {
                var toggle_part_contest_link = $('<i class="party-check fa-fw far" data-contest-id="' + event.id + '">&nbsp;</i>')
                toggle_part_contest_link.toggleClass(party_contests_set.has(parseInt(event.id))? 'fa-check-square' : 'fa-square')
                if (has_permission_toggle_party_contests) {
                    toggle_part_contest_link.click(toggle_party_contest)
                }
                toggle_part_contest_link.prependTo(element.querySelector('.fc-content'))
            }
            if (hide_contest) {
                var hide_contest_link=$('<i class="hide-contest fa fa-eye" data-contest-id="' + event.id + '">&nbsp;</i>')
                hide_contest_link.click(toggle_hide_contest)
                hide_contest_link.prependTo(element.querySelector('.fc-content'))
            }
            if (add_to_calendar && add_to_calendar.length == 1) {
                var data_ace = '{ "title":"' + event.title + '", "desc":"url: ' + event.url + '", "location":"' + event.extendedProps.host + '", "time":{ "start":"' + start_time + '", "end":"' + end_time + '", "zone":"' + timezone_hm + '" } }'
                var ace = $('<a onclick="return false" class="data-ace" data-ace=' + "'" + data_ace + "'" + '><i class="far fa-calendar-alt"></i></a>')
                $(ace).addcalevent({
                  'onclick': true,
                  'apps': [parseInt(add_to_calendar)],
                })
                ace.prependTo(element.querySelector('.fc-content'))
            }
        },
        eventClick: function (data, event, view) {
            return true
        },
        loading: function(bool) {
            $('#loading').toggle(bool)
        },
        eventLimit: event_limit,
        height: get_calendar_height()
    })

    calendar.render()

    $('.fc-button').addClass('btn btn-default btn-sm').removeClass('fc-button fc-button-primary')
    $('.fc-button-group').addClass('btn-group').removeClass('fc-button-group')

    for (var name in customButtonDesc) {
        var desc = customButtonDesc[name]
        $('.fc-' + name + '-button').attr('data-id', desc.data)
    }

    if (customButtonSelector) {
        $(customButtonSelector).toggleClass('ignore-filter')

        $btnGroup = $(customButtonSelector).first().parent()
        $btnGroup.html(
            '<button class="btn btn-default btn-sm dropdown-toggle" type="button" data-toggle="dropdown">Custom filters <span class="caret"></span></button><div class="dropdown-menu">'
            + $btnGroup.html() + '</div>'
        )

        $(customButtonSelector).click(function (e) {
            var $btn = $(this)
            var value = $btn.attr('data-value') || '0';
            $btn.attr('data-value', 1 - value)
            $btn.toggleClass('active')
            $btn.blur();
            e.preventDefault()
            calendar.refetchEvents()
            return false
        })
    }

    $('.fc-cb0-button').attr('id', 'spam-filter');
    $spam_filter = $('#spam-filter')
    $spam_filter.toggleClass('ignore-filter')
    $spam_filter.prop('checked', true)
    $spam_filter.bootstrapToggle({
        on: 'Filtered long',
        off: 'Disabled fitler',
        onstyle: 'default active',
        offstyle: 'default active',
        size: 'small',
        width: 106,
        height: 30,
    })


    $('.toggle:has(#spam-filter) .btn').click(function (e) {
        var value = $spam_filter.attr('data-value') || '0';
        $spam_filter.attr('data-value', 1 - value)
        $spam_filter.bootstrapToggle(parseInt(value)? 'on' : 'off')
        e.preventDefault()
        calendar.refetchEvents()
        return false
    })
})
