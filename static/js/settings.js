$(function() {
    $.fn.editable.defaults.mode = 'inline'
    $.fn.editable.defaults.url = '/settings/change/'

    $('#theme').editable({
        type: 'select',
        source: '/settings/search/?query=themes',
        showbuttons: false,
        display: function(value, sourceData, response) {
            if (response == 'accepted') {
                window.location.replace(PREFERENCES_URL);
            }
            if (value) {
                $(this).html(value.charAt(0).toUpperCase() + value.slice(1));
            }
        },
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select theme',
            val: editable.input.$input.val(),
        }).change(function() {
            setTimeout(function() { editable.input.$input.select2('close'); }, 1);
        })
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    })

    $('#timezone').editable({
        type: 'select',
        source: '/settings/search/?query=timezones',
        showbuttons: false,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select timezone',
            val: editable.input.$input.val(),

        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#preferences-tab .value [type="checkbox"]:not([data-on])').each(function() {
        $(this).attr('data-on', 'Enabled')
        $(this).attr('data-off', 'Disabled')
    })
    $('#preferences-tab .value [type="checkbox"]').each(function() {
        $(this).attr('checked', $(this).attr('data-value') == '1')
    }).bootstrapToggle({
        size: 'mini',
        width: 100,
        height: 20,
    }).change(function() {
        var $parent = $(this).parent().parent();
        if ($parent.find('.alert-danger').length == 0) {
            $parent.append('<div class="badge alert-danger" style="margin-left: 10px"></div>')
        }
        var $alert = $parent.find('.alert-danger')
        $alert.hide()
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: $(this).attr('id'),
                value: $(this).prop('checked'),
            },
            success: function() {
                $alert.hide()
            },
            error: function (xhr, status, errorThrown) {
                $alert.text(xhr.responseText)
                $alert.show()
            },
        })
    })

    $('#time-format').editable({ type: 'text', })

    $('#add-to-calendar').editable({
        type: 'select',
        showbuttons: false,
        source: ACE_CALENDARS,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select calendar type',
            val: editable.input.$input.val(),

        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#share-to-category').editable({
        type: 'select',
        showbuttons: false,
        source: SHARE_TO_CATEGORY,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select category',
            val: editable.input.$input.val(),
        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#past-action-in-calendar').editable({
        type: 'select',
        showbuttons: false,
        source: PAST_CALENDAR_ACTIONS,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select action',
            val: editable.input.$input.val(),
        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    event_limit_source = ['true', 'false']
    for (i = 1; i < 20; ++i) { event_limit_source.push(i.toString()) }
    $('#event-limit-calendar').editable({
        type: 'select',
        showbuttons: false,
        source: event_limit_source,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select event limit',
            val: editable.input.$input.val(),
        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#view-mode').editable({
        type: 'select',
        showbuttons: false,
        source: {'list': 'List', 'calendar': 'Calendar'},
    })

    $('#email').editable({
        type: 'select',
        source: emails,
        showbuttons: false,
    })

    $('#country').editable({
        type: 'select',
        source: COUNTRIES,
        showbuttons: false,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 300,
            placeholder: 'Select country',
            val: editable.input.$input.val(),
            templateResult: function (data) {
                var $result = $('<span></span>')
                $result.text(data.text)
                if (data.id) {
                    var code = data.id.toLowerCase()
                    $result.prepend('<div class="flag flag-' + code + '"></div>')
                }
                return $result
            },
            minimumInputLength: 0
        }).on('select2:select', function (e) {
            var country = e.params.data.id
            $('.custom-countries').addClass('hidden')
            $('.custom-countries[data-country="' + country + '"]').removeClass('hidden')
        })
        setTimeout(function() { editable.input.$input.select2('open'); }, 1)
    })


    $('.custom-countries').click(function() {
        var a = $(this)
        var country = a.data('country')
        var value = a.data('value')
        $('.custom-countries[data-country="' + country + '"]').blur()

        $('#custom_countries_loading').removeClass('hidden')

        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'custom-countries',
                country: country,
                value: value,
            },
            success: function(data) {
                $('.custom-countries[data-country="' + country + '"]').removeClass('active')
                $('.custom-countries[data-value="' + value + '"]').addClass('active')
                $('#custom_countries_loading').addClass('hidden')
            },
            error: function(data) {
                $.notify(data.responseText, 'error')
                $('#custom_countries_loading').addClass('hidden')
            },
        })
        return false
    })

    var Filter = function (options) {
        this.init('filter', options, Filter.defaults)
    }

    //inherit from Abstract input
    $.fn.editableutils.inherit(Filter, $.fn.editabletypes.abstractinput)

    $.extend(Filter.prototype, {
        render: function() {
            this.$input = this.$tpl.find('input')
            this.$resources = this.$tpl.find('#resources')
            this.$contest = this.$tpl.find('#contest')
            this.$party = this.$tpl.find('#party')
            this.$categories = this.$tpl.find('#categories')

            this.$tpl.find("i[rel=tooltip]")
                .addClass('far fa-question-circle')
                .tooltip({
                    placement: 'right',
                    delay: {show: 500, hide: 100},
                })

            this.$resources.select2({
                data: RESOURCES,
                multiple: true,
                width: '100%',
                placeholder: 'Select resources',
            })

            this.$contest.select2({
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select contest',
                ajax: {
                    url: '/settings/search/',
                    dataType: 'json',
                    delay: 314,
                    data: function (params) {
                        return {
                            query: 'notpast',
                            title: params.term,
                            page: params.page || 1
                        };
                    },
                    processResults: function (data, params) {
                        return {
                            results: data.items,
                            pagination: {
                                more: data.more
                            }
                        };
                    },
                    cache: true
                },
                minimumInputLength: 2,
            })

            this.$party.select2({
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select party',
                ajax: {
                    url: '/settings/search/',
                    dataType: 'json',
                    delay: 314,
                    data: function (params) {
                        return {
                            query: 'party',
                            name: params.term,
                            page: params.page || 1
                        };
                    },
                    processResults: function (data, params) {
                        return {
                            results: data.items,
                            pagination: {
                                more: data.more
                            }
                        };
                    },
                    cache: true
                },
                minimumInputLength: 2,
            })

            this.$categories.select2({
                data: CATEGORIES,
                multiple: true,
                width: '100%',
                placeholder: 'Select categories',
            })


            this.$tpl.find('#select-all-resources').click(function() {
                $('#resources').val($.map(RESOURCES, function(r) { return r.id })).trigger('change')
                return false
            })

            this.$tpl.find('#deselect-all-resources').click(function() {
                $('#resources').val([]).trigger('change')
                return false
            })

            this.$tpl.find('#inverse-resources').click(function() {
                $('#resources').val(
                    $.grep(
                        $.map(RESOURCES, function(resource) {
                            return resource.id
                        }),
                        function(id) {
                            return $.inArray(id, $('#resources').val()) === -1
                        }
                    )
                ).trigger('change')
                return false
            })
        },

        value2html: function(value, element) {
            if(!value) {
                $(element).empty()
                return
            }
            var html = ''
            if (value.name) {
                html += value.name + ': '
            }
            html += value.to_show? 'show ' : 'hide '
            if (value.resources && value.resources.length) {
                html += value.resources.length + ' resource(s)'
            }
            if (value.contest) {
                if (html.slice(-1) != ' ') {
                    html += ','
                }
                if (value.contest__title) {
                    html += ' contest ' + value.contest__title;
                } else {
                    html += ' contest_id ' + value.contest
                }
            }
            if (value.party) {
                if (html.slice(-1) != ' ') {
                    html += ','
                }
                if (value.party__name) {
                    html += ' party ' + value.party__name;
                } else {
                    html += ' party_id ' + value.party
                }
            }
            if (value.duration && (value.duration.from || value.duration.to)) {
                html +=
                    ', duration'
                    + (value.duration.from? ' from ' + value.duration.from : '')
                    + (value.duration.to? ' to ' + value.duration.to : '')
            }
            if (value.regex) {
                html += ', with ' + (value.inverse_regex? 'inverse ' : '') + 'regex ' + value.regex
            }
            $(element).html(html)
        },

        html2value: function(html) { return null },

        value2str: function(value) {
            return JSON.stringify(value)
        },

        str2value: function(str) {
            return str
        },

        value2input: function(value) {
            if (!value) {
                return
            }
            this.$input.filter('[name="name"]').val(value.name)
            this.$input.filter('[name="id"]').val(value.id)
            if (value.duration) {
                this.$input.filter('[name="duration-from"]').val(value.duration.from)
                this.$input.filter('[name="duration-to"]').val(value.duration.to)
            }
            this.$input.filter('[name="regex"]').val(value.regex)
            this.$input.filter('[name="inverse-regex"]').attr('checked', value.inverse_regex)
            this.$input.filter('[name="to-show"]').attr('checked', value.to_show)
            this.$contest.select2('trigger', 'select', {data: {id: value.contest, text: value.contest__title}})
            this.$party.select2('trigger', 'select', {data: {id: value.party, text: value.party__name}})
            this.$resources.val(value.resources).trigger('change')
            this.$categories.val(value.categories).trigger('change')
        },

        input2value: function() {
            contest_data = this.$contest.select2('data')
            party_data = this.$party.select2('data')
            result = {
                name: this.$input.filter('[name="name"]').val(),
                id: parseInt(this.$input.filter('[name="id"]').val()),
                duration: {
                    from: parseInt(this.$input.filter('[name="duration-from"]').val()),
                    to: parseInt(this.$input.filter('[name="duration-to"]').val()),
                },
                regex: this.$input.filter('[name="regex"]').val(),
                inverse_regex: this.$input.filter('[name="inverse-regex"]').prop('checked'),
                to_show: this.$input.filter('[name="to-show"]').prop('checked'),
                resources: $.map(this.$resources.val() || [], function (v) { return parseInt(v) }),
                contest: contest_data.length? contest_data[0].id : null,
                contest__title: contest_data.length? contest_data[0].text : null,
                party: party_data.length? party_data[0].id : null,
                party__name: party_data.length? party_data[0].text : null,
                categories: this.$categories.val() || [],
            }
            return result
        },

        activate: function () {
            this.$input[0].focus()
            this.$input.keypress(function (e) {
                if (e.which == 13) {
                    return false;
                }
            })
        },
    })

    Filter.defaults = $.extend({}, $.fn.editabletypes.abstractinput.defaults, {
        tpl: '\
<div> \
    <input type="hidden" name="id"> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Name</span> \
            <input name="name" maxlength="60" type="text" class="form-control"> \
        </div> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">To show</span> \
            <span class="input-group-addon"> \
                <input name="to-show" type="checkbox" rel="tooltip" title="To show"> \
            </span> \
        </div> \
        <div class="input-group input-group-sm select2-bootstrap-prepend select2-bootstrap-append"> \
            <select id="categories" class="form-control" name="categories[]"></select> \
        </div> \
    </div> \
    <div class="filter-field"> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Duration</span> \
            <span class="input-group-addon">from</span> \
            <input min="0" max="2139062143" type="number" class="form-control" name="duration-from"> \
            <span class="input-group-addon">to</span> \
            <input min="0" max="2139062143" type="number" class="form-control" name="duration-to"> \
            <span class="input-group-addon">minute(s)</span> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Regex</span> \
            <input name="regex" maxlength="1000" type="text" class="form-control"> \
        </div> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Inverse regex</span> \
            <span class="input-group-addon"> \
                <input name="inverse-regex" type="checkbox" rel="tooltip" title="Inverse regex"> \
            </span> \
        </div> \
        <i rel="tooltip" title="Use `url:#regex#` to filter by regex by url"></i> \
    </div> \
    <div class="filter-field"> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Resources</span> \
            <span class="input-group-btn"> \
                <button id="select-all-resources" class="btn btn-default"><i class="fa fa-check"></i></button> \
                <button id="deselect-all-resources" class="btn btn-default"><i class="fa fa-times"></i></button> \
                <button id="inverse-resources" class="btn btn-default" title="inverse"><i class="fas fa-sync-alt"></i></button> \
            </span> \
        </div> \
        <div class="filter-field-resources"> \
            <select id="resources" class="form-control" name="resources[]"></select> \
        </div> \
    </div> \
    <div class="h5">OR</div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Contest</span> \
            <select id="contest" class="form-control" name="contest"></select> \
        </div> \
        <i rel="tooltip" title="Use `Hide contest` option in preferences for a simple way to create contest filter"></i> \
    </div> \
    <div class="h5">OR</div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Party</span> \
            <select id="party" class="form-control" name="party"></select> \
        </div> \
    </div> \
</div> \
        ',
        inputclass: '',
    })

    $.fn.editabletypes.filter = Filter

    filterEditableOptions = {
        type: 'filter',
        showbuttons: 'bottom',
        error: function(data) {
            $('.editable-error-block')
                .addClass('alert')
                .addClass('alert-danger')
                .html(data.responseText).show()
        },
    }

    function filterEditableShown(e, editable) {
        $('[data-id="{0}"]'.format(editable.value.id)).addClass('hidden')
    }

    function filterEditableHidden(e, editable) {
        var $button = $('[data-id="{0}"]'.format($(this).data('editable').value.id))
        if ($(this).data('editable').value.resources.length == 0
            && !$(this).data('editable').value.contest
            && !$(this).data('editable').value.party
        ) {
            $button.click()
        } else {
            $button.removeClass('hidden')
        }
    }

    $('.filter').editable(filterEditableOptions)
    $('.filter').on('shown', filterEditableShown)
    $('.filter').on('hidden', filterEditableHidden)

    $('#add-filter-error').click(function() {
        $(this).addClass('hidden')
    })

    $('#add-filter').click(function() {
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'add-filter',
            },
            success: function(data) {
                var $div = $('\
<div> \
    <a href="#" class="filter" data-name="filter" data-value=\'' + JSON.stringify(data) + '\'></a> \
    <a href="#" data-id="' + data.id + '" data-action="delete-filter" data-success="$div.remove();" class="action-filter btn btn-default btn-xs"> \
        <i class="far fa-trash-alt"></i> \
    </a> \
</div> \
                ')
                $div.find('.filter').editable(filterEditableOptions)
                $div.find('.filter').on('shown', filterEditableShown)
                $div.find('.filter').on('hidden', filterEditableHidden)

                $div.find('.action-filter').click(sentAction)
                $div.prependTo('#filters')
                $div.find('.filter').click()
            },
            error: function(data) {
                $('#add-filter-error').removeClass('hidden').html(data.responseText)
            },
        })
        return false
    })

    function process_list() {
        name = $(this).attr('data-name')
        id = $(this).attr('data-id') || ''
        bootbox.prompt({title: 'List name', value: $(this).attr('data-value'), callback: function(result) {
            if (!result) {
                return;
            }
            $.ajax({
                type: 'POST',
                url: $.fn.editable.defaults.url,
                data: {
                    pk: $.fn.editable.defaults.pk,
                    name: name,
                    value: result,
                    id: id,
                },
                success: function(data) {
                    window.location.replace(LISTS_URL);
                },
                error: function(response) {
                    log_ajax_error(response)
                },
            })
        }});
    }

    $('#add-list').click(process_list)
    $('.edit-list').click(process_list)

    function process_calendar() {
        name = $(this).attr('data-name')
        id = $(this).attr('data-id') || ''
        value = $(this).attr('data-value') || ''
        category = $(this).attr('data-category') || ''
        resources = JSON.parse($(this).attr('data-resources') || "[]")
        descriptions = JSON.parse($(this).attr('data-descriptions') || "[]")

        var category_select = '<option></option>'
        CATEGORIES.forEach(el => { category_select += '<option value="' + el['id'] + '"' + (category == el['id']? ' selected' : '') + '>' + el['text'] + '</option>' })

        var resources_select = ''
        RESOURCES.forEach(el => { resources_select += '<option value="' + el['id'] + '"' + ($.inArray(parseInt(el['id']), resources) !== -1? ' selected' : '') + '>' + el['text'] + '</option>' })

        var descriptions_select_after = ''
        var descriptions_options = {}
        EVENT_DESCRIPTIONS.forEach(el => {
            var has = $.inArray(parseInt(el['id']), descriptions) !== -1
            var option = '<option value="' + el['id'] + '"' + (has? ' selected' : '') + '>' + el['text'] + '</option>'
            if (has) {
                descriptions_options[el['id']] = option
            } else {
                descriptions_select_after += option
            }
        })
        var descriptions_select_before = ''
        descriptions.forEach(id => { descriptions_select_before += descriptions_options[id] })
        var descriptions_select = descriptions_select_before + descriptions_select_after

        var form = $(`
          <form>
            <div class="form-group">
              <label class="control-label">Calendar name</label>
              <input class="form-control" placeholder="Name" autocomplete="off" name="name" value="` + value + `" required maxlength="64">
              <small class="form-text text-muted">Required field</small>
            </div>
            <div class="form-group">
              <label class="control-label">Filter</label>
              <select class="form-control" name="category">` + category_select + `</select>
              <small class="form-text text-muted">Used to filter contests. Configure <a href="` + FILTERS_URL + `" target="_blank">here</a>. Optional field</small>
            </div>
            <div class="form-group">
              <label class="control-label">Resources <a class="inverse-resources btn btn-default btn-xs" title="inverse"><i class="fas fa-sync-alt"></i></a></label>
              <select class="form-control" name="resources" multiple>` + resources_select + `</select>
              <small class="form-text text-muted">Additional filter for resource. Full list <a href="` + RESOURCES_URL + `" target="_blank">here</a>. Optional field</small>
            </div>
            <div class="form-group">
              <label class="control-label">Event description</label>
              <select class="form-control" name="descriptions" multiple>` + descriptions_select + `</select>
              <small class="form-text text-muted">Order sensitive. Optional field</small>
            </div>
          </form>
        `);
        form.find('select').select2({width: '100%'})
        var $select_descriptions = $(form.find('select[name=descriptions]')[0])
        $select_descriptions.select2({
            width: '100%',
            sorter: function(items) {
                var sorted_items = []
                items.forEach((item, idx) => {
                    sorted_items[item.sorter_index ?? idx] = item
                })
                ret = []
                ret.push(...sorted_items.filter(i => i.selected ))
                ret.push(...sorted_items.filter(i => !i.selected ))
                var new_order = {}
                ret.forEach((item, idx) => {
                    item.sorter_index = idx
                    new_order[item.id] = idx
                })
                var new_options = []
                $options = $select_descriptions.children('option').detach()
                $options.each((idx, option) => {
                    var $option = $(option)
                    var id = $option.attr('value')
                    new_options[new_order[id]] = $option
                })
                $select_descriptions.append(new_options)
                $select_descriptions.trigger('change.select2')
                return ret
            },
        })

        form.find('.inverse-resources').click(() => {
            var resources = form.find('select[name=resources]')
            resources.val(
                $.grep(
                    $.map(RESOURCES, function(resource) { return resource.id }),
                    function(id) { return $.inArray(id, resources.val()) === -1 }
                )
            ).trigger('change')
            return false
        })

        bootbox.confirm(form, function(result) {
            if (!result) {
                return;
            }
            var input = form.find('input[name=name]')
            if (!input[0].checkValidity()) {
                input.closest('.form-group').addClass('has-error')
                return false;
            }
            value = form.find('input[name=name]').val()
            category = form.find('select[name=category]').val()
            resources = form.find('select[name=resources]').val()
            descriptions = form.find('select[name=descriptions]').val()
            $.ajax({
                type: 'POST',
                url: $.fn.editable.defaults.url,
                data: {
                    pk: $.fn.editable.defaults.pk,
                    name: name,
                    value: value,
                    category: category,
                    resources: resources,
                    descriptions: descriptions,
                    id: id,
                },
                success: function(data) {
                    window.location.replace(CALENDARS_URL);
                },
                error: function(response) {
                    log_ajax_error(response)
                },
            })
        })
        $('.bootbox.modal').removeAttr('tabindex')
    }

    function copy_calendar_url() {
        copyTextToClipboard($(this).attr('data-url'))
        var help = $(this).parent().find('.copy-url-help')
        help.removeClass('hidden')
        help.fadeIn('fast')
        setTimeout(() => help.fadeOut('slow'), 1000)
    }

    $('#add-calendar').click(process_calendar)
    $('.edit-calendar').click(process_calendar)
    $('.copy-calendar-url').click(copy_calendar_url)

    var ntf_form = $('#notification-form')
    var ntf_add = $('#add-notification')
    $('.edit-notification').click(function() {
        var ntf = $(this).closest('.notification')
        ntf_form.find('[name="pk"]').val($(this).attr('data-id'))
        ntf_form.find('[name="method"]').val(ntf.find('[data-value="method"]').attr('data-val'))
        ntf_form.find('[name="period"]').val(ntf.find('[data-value="period"]').text())
        ntf_form.find('[name="before"]').val(ntf.find('[data-value="before"]').text())
        ntf_form.find('[name="with_updates"]').prop('checked', ntf.find('[data-value="updates"]').length)
        ntf_form.find('[name="with_results"]').prop('checked', ntf.find('[data-value="results"]').length)
        ntf_form.find('[name="with_virtual"]').prop('checked', ntf.find('[data-value="virtual"]').length)
        ntf_form.find('[name="add"]').val('Update')
        ntf_add.remove()
        ntf_form.show(300)
    })

    function sentAction() {
        var $this = $(this)
        var $div = $this.parent()
        bootbox.confirm({
            size: 'small',
            message: $div.text() +
                "<br/><br/>" +
                "<b>" + $this.attr('data-action').replace('-', ' ').toTitleCase() + "?</b>",
            callback: function(result) {
                if (result) {
                    $.ajax({
                        type: 'POST',
                        url: $.fn.editable.defaults.url,
                        data: {
                            pk: $.fn.editable.defaults.pk,
                            name: $this.attr('data-action'),
                            id: $this.data("id"),
                        },
                        success: function(data) {
                            eval($this.attr('data-success'))
                        },
                        error: function(data) {
                            $.notify("{status} {statusText}: {responseText}".format(data), "error");
                        },
                    })
                }
            }
        })
        return false
    }
    $('.action-notification').click(sentAction)
    $('.action-filter').click(sentAction)
    $('.action-list').click(sentAction)
    $('.action-calendar').click(sentAction)

    $("i[rel=tooltip]")
        .addClass('far fa-question-circle')
        .tooltip({
            placement: 'right',
            delay: {show: 500, hide: 100},
        })

    $('#first-name').editable({ type: 'text', })
    $('#last-name').editable({ type: 'text', })
    $('#first-name-native').editable({ type: 'text', })
    $('#last-name-native').editable({ type: 'text', })

    var $resource = $('select#add-account-resource')
    $resource.select2({
        width: '40%',
        allowClear: true,
        placeholder: 'Search resource by regex',
        data: SELECTED_RESOURCE,
        ajax: {
            url: '/settings/search/',
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return {
                    query: 'resources-for-add-account',
                    regex: params.term,
                    page: params.page || 1
                };
            },
            processResults: function (data, params) {
                return {
                    results: data.items,
                    pagination: {
                        more: data.more
                    }
                };
            },
        },
        minimumInputLength: 0
    })

    $errorAccountTab = $('#error-account-tab')
    var $listAccount = $('#list-accounts')

    function deleteAccount() {
        var $this = $(this)
        var $account = $this.closest('.account')
        bootbox.confirm({
            size: 'small',
            message: $account.text() + "<br/><br/><b>Delete Account?</b>",
            callback: function(result) {
                if (result) {
                    $.ajax({
                        type: 'POST',
                        url: $.fn.editable.defaults.url,
                        data: {
                            pk: $.fn.editable.defaults.pk,
                            name: 'delete-account',
                            id: $account.find('.delete-account').attr('data-id'),
                        },
                        success: function(data) {
                            $account.remove()
                        },
                        error: function(data) {
                            $errorAccountTab.show().html(data.responseText)
                            setTimeout(function() { $errorAccountTab.hide(500) }, 3000)
                        },
                    })
                }
            }
        })
    }

    function addAccount(index, element) {
        var h4 = $('<h4>')
            .append($('<a>', {class: 'delete-account btn btn-default btn-xs'}).attr('data-id', element.pk).append($('<i>', {class: 'far fa-trash-alt'})))
            .append($('<span>', {text: ' '}))
            .append($('<span>', {text: element.account + (element.name && element.account.indexOf(element.name) == -1? ' | ' + element.name : '')}))
            .append($('<span>', {text: ' '}))
            .append($('<a>', {class: 'small', href: 'http://' + element.resource, text: element.resource}))

        var $block = $('<div class="account">').append(h4)
        $block.find('.delete-account').click(deleteAccount)
        $listAccount.prepend($block)
    }
    $('.delete-account').click(deleteAccount)

    var $search = $('#add-account-search')
    $search.css({'width': '40%'});

    var $button = $('#add-account')
    var $loading = $('#add-account-loading')

    function update_advanced_search() {
        $advanced_search = $('#add-account-advanced-search')
        href = ACCOUNTS_ADVANCED_SEARCH_URL
        if ($resource.val()) {
            href += '&resource=' + $resource.val()
        }
        if ($search.val()) {
            href += '&search=' + encodeURIComponent($search.val())
        }
        $advanced_search.attr('href', href)
    }
    $resource.on('change', update_advanced_search)
    $search.on('keyup', update_advanced_search)
    update_advanced_search()

    $button.click(function() {
        $loading.removeClass('hidden')
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'add-account',
                resource: $resource.val(),
                value: $search.val(),
            },
            success: function(data) {
                $loading.addClass('hidden')
                addAccount(-1, data)
                $resource.val(null).trigger('change');
                $search.val(null).trigger('change');

            },
            error: function(data) {
                $loading.addClass('hidden')
                $errorAccountTab.show().html(data.responseText)
                setTimeout(function() { $errorAccountTab.hide(500) }, 3000)
            },
        })
    })

    $search.keypress(function(e) {
        if (e.which == 13 ) {
            e.preventDefault()
            $button.click()
        }
    })

    var $search_org = $('#organization-search')
    $search_org.select2({
        width: '50%',
        ajax: {
            url: '/settings/search/',
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return {
                    query: 'organization',
                    name: params.term,
                    page: params.page || 1
                };
            },
            processResults: function (data, params) {
                return {
                    results: data.items,
                    pagination: {
                        more: data.more
                    }
                };
            },
            cache: true
        },
        minimumInputLength: 0
    })

    var $delete_user = $('#delete-user')
    $delete_user.click(function() {
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'pre-delete-user',
            },
            success: function(data) {
                bootbox.prompt({
                    size: 'medium',
                    title: 'Delete user?',
                    message: 'Data to be deleted:<pre>' + data.data + '</pre>Enter your username to be deleted:',
                    callback: function(result) {
                        if (result) {
                            $.ajax({
                                type: 'POST',
                                url: $.fn.editable.defaults.url,
                                data: {
                                    pk: $.fn.editable.defaults.pk,
                                    username: result,
                                    name: 'delete-user',
                                },
                                success: function(data) {
                                    document.location.href = "/"
                                },
                                error: function(data) {
                                    $.notify(data.responseText, "error")
                                },
                            })
                        }
                    },
                    onShown: function(e) {
                        var btn = $('.btn.btn-danger.bootbox-accept')
                        btn.addClass('disabled')
                        $('.bootbox-input-text').keyup(function() {
                            if ($(this).val() == USERNAME) {
                                btn.removeClass('disabled')
                            } else {
                                btn.addClass('disabled')
                            }
                        })
                    },
                    buttons: {
                        confirm: {
                            label: 'Delete user',
                            className: 'btn-danger',
                        },
                    },
                })
            },
            error: function(data) {
                $.notify(data.responseText, "error")
            },
        })
    })
})
