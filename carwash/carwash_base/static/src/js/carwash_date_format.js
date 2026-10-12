import { registry } from "@web/core/registry";
import "@web/views/fields/formatters";
import "@web/views/fields/datetime/list_datetime_field";

/**
 * Odoo 19 shows read-only dates in a short human style ("Oct 6") and only uses the
 * language's Date Format (Settings > Languages) when a field has options="{'numeric': true}".
 * The car wash wants every date in the language format (06 Oct, 26), so "numeric" becomes the
 * default for all date / datetime fields, list cells, kanban cards and pivot / group headers.
 * A view can still opt out with options="{'numeric': false}".
 */
const withNumeric = (options) => ({ ...(options || {}), numeric: options?.numeric ?? true });

const fields = registry.category("fields");
for (const name of ["date", "datetime", "daterange", "list.date", "list.datetime", "list.daterange"]) {
    const field = fields.get(name, null);
    if (!field) {
        continue;
    }
    fields.add(
        name,
        {
            ...field,
            extractProps: (fieldInfo, dynamicInfo) =>
                field.extractProps({ ...fieldInfo, options: withNumeric(fieldInfo.options) }, dynamicInfo),
            listViewWidth: (fieldInfo) =>
                field.listViewWidth({ ...fieldInfo, options: withNumeric(fieldInfo.options) }),
        },
        { force: true }
    );
}

const formatters = registry.category("formatters");
for (const type of ["date", "datetime"]) {
    const formatter = formatters.get(type);
    const numericFormatter = (value, options = {}) => formatter(value, withNumeric(options));
    numericFormatter.extractOptions = (fieldInfo) =>
        formatter.extractOptions({ ...fieldInfo, options: withNumeric(fieldInfo.options) });
    formatters.add(type, numericFormatter, { force: true });
}
