function filterCallbackCalendar() {
    calendar.refetchEvents()
}

$(function() {

    var bottom_pad = 20

    function get_calendar_height() {
        return $(window).height() - ($('#calendar').closest('.tab-content').position().top + bottom_pad)
    }

    $(window).resize(function() {
        var height = get_calendar_height()
        calendar.setOption('height', height)
        calendar.setOption('contentHeight', height)

        $('.fc-timegrid').each(function() {
            var el = $(this).find('.fc-scroller:has(.fc-timegrid-body)')
            var height = el.height()
            var tr = $(this).find('.fc-timegrid-slots tr')
            tr.height(height / tr.length)
        })
    })

    function after_render() {
        stylize_button()
        $(window).trigger('resize')
    }

    function stylize_button() {
        $('.fc-button').addClass('btn btn-default btn-sm').removeClass('fc-button fc-button-primary')
        $('.fc-button-group').addClass('btn-group').removeClass('fc-button-group')

        if (customButtonSelector) {
            $(customButtonSelector).hide()
            $('.dropdown-menu').find(customButtonSelector).show()
        }

        if (calendar.view.type === 'fiveDayWindow') {
            calendar_el.querySelector('.fc-prev-button').style.visibility = 'hidden'
            calendar_el.querySelector('.fc-next-button').style.visibility = 'hidden'
        } else {
            calendar_el.querySelector('.fc-prev-button').style.visibility = 'visible'
            calendar_el.querySelector('.fc-next-button').style.visibility = 'visible'
        }
    }

    var hour12 = is_12_hour_clock()
    var time_format = {
        hour: 'numeric',
        minute: '2-digit',
        meridiem: hour12? 'short' : false,
        hour12: hour12,
    }

    var calendar_views = {
        dayGridMonth: {},
        timeGridWeek: {},
        listWeek: {},
        multiMonthYear: {},
        fiveDayWindow: {
            type: 'timeGrid',
            buttonText: '5days',
            visibleRange: function(current_date) {
                let start_date = new Date(current_date);
                start_date.setDate(start_date.getDate() - 1);
                let end_date = new Date(current_date);
                end_date.setDate(end_date.getDate() + 3);
                return {start: start_date, end: end_date};
            },
        },
    }
    var calendar_view = Cookies.get('calendar_view')
    if (!(calendar_view in calendar_views)) {
        calendar_view = Object.keys(calendar_views)[0];
    }

    var calendar_el = document.getElementById('calendar')
    calendar = new FullCalendar.Calendar(calendar_el, {
        views: calendar_views,
        initialView: calendar_view,
        nowIndicator: true,
        customButtons: customButtonDesc,
        eventDisplay: 'block',
        headerToolbar: {
            left: 'title',
            right: customButtonGroup + ' today,dayGridMonth,timeGridWeek,listWeek,multiMonthYear,fiveDayWindow prev,next'
        },
        titleFormat: { year: 'numeric', month: 'long', day: 'numeric' },
        firstDay: 1,
        allDaySlot: true,
        timeZone: timezone,
        eventTimeFormat: time_format,
        slotLabelFormat: time_format,
        slotDuration: '01:00',
        slotLabelInterval: '01:00',
        events: function (fetchInfo, successCallback, failureCallback) {
            var url = new URL(window.location.href)
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
                    resource: url.searchParams.getAll('resource'),
                    status: url.searchParams.get('status'),
                    favorite: $('#filter button[name="favorite"].active').data('value'),
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
        eventDidMount: function (info) {
            var event = info.event
            var element = info.el
            var start = FullCalendar.Moment.toMoment(event.start, calendar)
            var end = FullCalendar.Moment.toMoment(event.end, calendar)
            var now = FullCalendar.Moment.toMoment($.now(), calendar)
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

            var event_element
            var is_list = false
            if (calendar.view.type == 'timeGridWeek' || calendar.view.type == 'fiveDayWindow') {
                event_element = $(element).find('.fc-event-title')[0]
            } else if (calendar.view.type == 'listWeek') {
                event_element = $(element).find('.fc-list-event-title')[0]
                is_list = true
            } else {
                event_element = $(element).find('.fc-event-main-frame')[0]
            }

            var addition_info = $('<span></span>')

            var icon = $('<img src="' + main_host_url + '/media/sizes/32x32/' + event.extendedProps.icon + '" height="18" width="18">&nbsp;</img>')
            icon.prependTo(addition_info)

            if (contest_toggle) {
                var toggle_part_contest_link = $('<i class="party-check fa-fw far" data-contest-id="' + event.id + '">&nbsp;</i>')
                toggle_part_contest_link.toggleClass(party_contests_set.has(parseInt(event.id))? 'fa-check-square' : 'fa-square')
                if (has_permission_toggle_party_contests) {
                    toggle_part_contest_link.click(toggle_party_contest)
                }
                toggle_part_contest_link.prependTo(addition_info)
            }
            if (favorite_contests && !is_list) {
                var icon_class = event.extendedProps.favorite? 'selected-activity fas' : 'far'
                var favorite_data = 'data-activity-type="fav" data-content-type="contest" data-object-id="' + event.id + '" data-selected-class="fas" data-unselected-class="far"'
                var favorite_icon = $('<i onclick="click_activity(event, this)" class="activity fa-star fav ' + icon_class + '" ' + favorite_data + '></i>')
                favorite_icon.prependTo(addition_info)
            }
            if (hide_contest && !is_list) {
                var hide_contest_link=$('<i onclick="toggle_hide_contest(event, this)" class="hide-contest fa fa-eye" data-contest-id="' + event.id + '">&nbsp;</i>')
                hide_contest_link.prependTo(addition_info)
            }
            if (add_to_calendar && add_to_calendar.length == 1 && !is_list) {
                var data_ace = '{ "title":"' + event.title + '", "desc":"url: ' + event.url + '", "location":"' + event.extendedProps.host + '", "time":{ "start":"' + start_time + '", "end":"' + end_time + '", "zone":"' + timezone_hm + '" } }'
                var ace = $('<a onclick="return false" class="data-ace" data-ace=' + "'" + data_ace + "'" + '><i class="far fa-calendar-alt"></i></a>')
                $(ace).addcalevent({
                  'onclick': true,
                  'apps': [parseInt(add_to_calendar)],
                })
                ace.prependTo(addition_info)
            }

            addition_info.prependTo(event_element)
        },
        viewDidMount: function() {
            Cookies.set('calendar_view', calendar.view.type)
            after_render()
        },
        datesSet: function() {
            Cookies.set('calendar_view', calendar.view.type)
            after_render()
        },
        eventClick: function (data, event, view) {
            return true
        },
        loading: function(bool) {
            $('#loading').toggle(bool)
        },
        dayMaxEventRows: event_limit,
        height: get_calendar_height(),
    })

    calendar.render()

    for (var name in customButtonDesc) {
        var desc = customButtonDesc[name]
        $('.fc-' + name + '-button').attr('data-id', desc.data)
    }

    if (customButtonSelector) {
        $(customButtonSelector).toggleClass('ignore-filter')

        $btnGroup = $(customButtonSelector).first().parent()
        $btnGroup.html(
            '<button class="btn btn-default btn-sm dropdown-toggle" type="button" data-toggle="dropdown">Custom filters <span class="caret"></span></button>'
            + '<div class="dropdown-menu">' + $btnGroup.clone().html() + '</div>'
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

    $('.fc-cb0-button').attr('id', 'spam-filter').addClass('hidden');
    $spam_filter = $('#spam-filter')
    $spam_filter.wrap('<div class="btn-group"></div>')
    $spam_filter.toggleClass('ignore-filter')
    $spam_filter.prop('checked', true)
    $spam_filter.bootstrapToggle({
        on: 'Filtered long',
        off: 'Disabled filter',
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

    after_render()
})
