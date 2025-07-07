import asyncio
import logging
import json
import tabulate
import textwrap

from reprint import output

from iact3.logger import PrintMsg
from iact3.stack import Stacker

LOG = logging.getLogger(__name__)


class TerminalPrinter:
    def __init__(self, minimalist=False):
        self.minimalist = minimalist
        if not minimalist:
            self._buffer_type = "list"
            self.buffer = self._add_buffer()

    def _add_buffer(self):
        with output(output_type=self._buffer_type) as output_buffer:
            return output_buffer

    async def report_test_progress(self, stacker: Stacker, poll_interval=10):
        if self.minimalist:
            await self.minimalist_progress(stacker, poll_interval)
            return
        _status_dict = stacker.status()
        while self._is_test_in_progress(_status_dict):
            for stack in stacker.stacks:
                self._print_stack_tree(stack, buffer=self.buffer)
            await asyncio.sleep(poll_interval)
            self.buffer.clear()
            _status_dict = stacker.status()

        self._display_final_status(stacker)

    async def minimalist_progress(self, stacker: Stacker, poll_interval):
        _status_dict = stacker.status()
        history: dict = {}
        while self._is_test_in_progress(_status_dict):
            _status_dict = stacker.status()
            for stack in stacker.stacks:
                self._print_tree_minimal(stack, history)
            await asyncio.sleep(poll_interval)

    @staticmethod
    def _print_tree_minimal(stack, history):
        if stack.id not in history:
            history[stack.id] = ""
        if history[stack.id] != stack.status:
            history[stack.id] = stack.status
            msg = f"{stack.test_name} {stack.region} {stack.status}"
            if "FAILED" in stack.status:
                LOG.error(msg)
                for event in stack.error_events(refresh=True):
                    LOG.error(f"    {event.logical_id} {event.status_reason}")
            else:
                LOG.info(msg)

    @staticmethod
    def _print_stack_tree(stack, buffer):
        padding_1 = "         "
        buffer.append("{}{}stack {} {}".format(padding_1, "\u250f ", "\u24c2", stack.name))
        buffer.append("{}{} region: {}".format(padding_1, "\u2523", stack.region))
        buffer.append("{}{} id: {}".format(padding_1, "\u2523", stack.id or ''))
        buffer.append(
            "{}{}status: {}{}{}".format(
                padding_1, "\u2517 ", PrintMsg.white, stack.status, PrintMsg.rst_color
            )
        )

    @staticmethod
    def _display_final_status(stacker):
        for final_stack in stacker.stacks:
            LOG.info("{}stack {} {}".format("\u250f ", "\u24c2", final_stack.name))
            LOG.info("{} region: {}".format("\u2523", final_stack.region))
            LOG.info("{} id: {}".format("\u2523", final_stack.id or ''))
            out_puts = final_stack.outputs
            if out_puts:
                LOG.info(
                    "{}status: {}{} {}".format(
                        "\u2523 ", PrintMsg.white, final_stack.status, PrintMsg.rst_color)
                )
                LOG.info("{}outputs: {}".format("\u2517 ", json.dumps(out_puts)))
            else:
                LOG.info(
                    "{}status: {}{} {}".format(
                        "\u2517 ", PrintMsg.white, final_stack.status, PrintMsg.rst_color
                    )
                )

    @staticmethod
    def _display_price(stacker):
        def _format_association_price(price_dict: dict, result: list, association_product: str):
            if price_dict:
                for k, v in price_dict.items():
                    association_prefix = association_product
                    if isinstance(v, dict) and "Result" in v:
                        association_prefix = v["Type"][v["Type"].index("::")+2:] if "Type" in v else association_product
                        try:
                            association_price = {
                                "Type": f'{association_product}-{k}' if not "Type" in v else v["Type"],
                                "ChargeType": v["Result"]["OrderSupplement"]["ChargeType"],
                                "PeriodUnit": v["Result"]["OrderSupplement"]["PriceUnit"],
                                "Quantity": v["Result"]["OrderSupplement"]["Quantity"],
                                "Currency": v["Result"]["Order"]["Currency"],
                                "OriginalAmount": v["Result"]["Order"]["OriginalAmount"] if "OriginalAmount" in v["Result"]["Order"] else None,
                                "DiscountAmount": v["Result"]["Order"]["DiscountAmount"] if "DiscountAmount" in v["Result"]["Order"] else None,
                                "TradeAmount": v["Result"]["Order"]["TradeAmount"],
                            }
                            result.append(association_price)
                        except Exception:
                            pass
                    if isinstance(v, dict):
                        _format_association_price(v, result, association_prefix)

        for stack in stacker.stacks:
            test_name = f' test_name: {stack.test_name} '
            line_width_default = 140
                  
            if stack.template_price:
                price_detail = []
                for k,v in stack.template_price.items():
                    try:
                        resource_price = {
                            "Resource": k,
                            "Region": stack.region,
                            "Type": v["Type"],
                            "ChargeType": v["Result"]["OrderSupplement"]['ChargeType'],
                            "PeriodUnit": v["Result"]["OrderSupplement"]['PriceUnit'],
                            "Quantity": v["Result"]["OrderSupplement"]['Quantity'],
                            "Currency": v["Result"]["Order"]["Currency"],
                            "OriginalAmount": v["Result"]["Order"]["OriginalAmount"] if "OriginalAmount" in v["Result"]["Order"] else None,
                            "DiscountAmount": v["Result"]["Order"]["DiscountAmount"] if "DiscountAmount" in v["Result"]["Order"] else None,
                            "TradeAmount": v["Result"]["Order"]["TradeAmount"] if "TradeAmount" in v["Result"]["Order"] else None
                        }
                        price_detail.append(resource_price)
                    except Exception:
                        resource_price = {
                            "Resource": k,
                            "Region": stack.region,
                            "Type": v["Type"],
                            "ChargeType": None,
                            "PeriodUnit": None,
                            "Quantity": None,
                            "Currency": None,
                            "OriginalAmount": None,
                            "DiscountAmount": None,
                            "TradeAmount": None
                        }
                        price_detail.append(resource_price)
                        pass

                    _format_association_price(v["Result"],price_detail,v["Type"][v["Type"].index("::")+2:])
                    
                tab = tabulate.tabulate(price_detail, headers="keys")
                tab_lines = tab.splitlines() 
                tab_width = len(tab_lines[1])

                test_name = test_name.ljust(int(tab_width/2) + int(len(test_name)/2) + 1, "\u2501")
                test_name = test_name.rjust(tab_width + 2, "\u2501")
                LOG.info("{}{}{}{}{} ".format("\u250f", PrintMsg.blod, 
                                                test_name, "\u2513", PrintMsg.rst_color)) 

                for i, line in enumerate(tab_lines):
                    LOG.info("{} {} {}".format("\u2523" if i != len(tab_lines)-1 else "\u2517", 
                                                 line.ljust(tab_width," "), 
                                                 "\u252B" if i != len(tab_lines)-1 else "\u251B"))
                LOG.info("\n")
            if not stack.template_price:
                test_name = test_name.ljust(int(line_width_default/2)+int(len(test_name)/2)-1, "\u2501")
                test_name = test_name.rjust(line_width_default-1 , "\u2501")
                LOG.info("{}{}{}{}{} ".format("\u250f", PrintMsg.blod, 
                                                test_name, "\u2513", PrintMsg.rst_color)) 
                LOG.info(
                    "{} status: {}{}{} ".format(
                    "\u2523", PrintMsg.text_red_background_write, 
                    (stack.status + PrintMsg.rst_color).ljust(line_width_default-len(" status: ")+len(PrintMsg.rst_color)-1,' '), 
                    "\u252B"
                ))
                subsequent_indent = ' ' * 28
                status_reason = textwrap.fill(stack.status_reason, width=line_width_default-16, break_long_words=False, replace_whitespace=True, subsequent_indent=subsequent_indent)
                status_reason = PrintMsg.text_red_background_write + status_reason.replace('\n', f'{PrintMsg.rst_color}\n{PrintMsg.text_red_background_write}').replace(subsequent_indent,f'{PrintMsg.rst_color}{subsequent_indent}{PrintMsg.text_red_background_write}') + PrintMsg.rst_color
                LOG.info("{} status reason: {} {}\n".format("\u2517", status_reason, PrintMsg.rst_color))
    
    @staticmethod
    def _display_validation(template_validation: dict):
        result_json =  {
            "validate_result": template_validation["Code"] if "Code" in template_validation else 'LegalTemplate',
            "result_reason": template_validation["Message"] if "Message" in template_validation else 'Check passed'
        }
        tab = tabulate.tabulate([result_json], headers="keys")
        tab_lines = tab.splitlines() 
        for i, line in enumerate(tab_lines):
            if i >= 2 and result_json['validate_result'] != 'LegalTemplate':
                LOG.error(f'{PrintMsg.text_red_background_write}{line}{PrintMsg.rst_color}')    
            else:
                LOG.info(line)

    @staticmethod
    def _display_preview_resources(stacker):
        line_width_default = 90
        for stack in stacker.stacks:
            test_name = f' test_name: {stack.test_name} '
            if stack.preview_result:
                resources_details = []
                for r in stack.preview_result:
                    resources_json = {
                        "LogicalResourceId": r["LogicalResourceId"],
                        "ResourceType": r["ResourceType"][r["ResourceType"].index("::")+2:],
                    }
                    properties_str = json.dumps(r["Properties"], sort_keys=True, indent=4, separators=(',', ': '), ensure_ascii=False)
                    resources_json["Properties"] = properties_str
                
                    resources_details.append(resources_json)
                
                tab = tabulate.tabulate(resources_details, headers="keys")
                tab_lines = tab.splitlines() 
                tab_width = len(tab_lines[1])

                test_name = test_name.ljust(int(tab_width/2) + int(len(test_name)/2) + 1, "\u2501")
                test_name = test_name.rjust(tab_width + 2, "\u2501")
                
                LOG.info(f'{PrintMsg.left_top}{PrintMsg.blod}{test_name}{PrintMsg.right_top}{PrintMsg.rst_color}')
                LOG.info(f'{PrintMsg.left} region: {stack.region.ljust(tab_width-len("region: ")," ")} {PrintMsg.right}')
                for i, line in enumerate(tab_lines):             
                    LOG.info(f'{PrintMsg.left if i != len(tab_lines)-1 else PrintMsg.left_bottom} {line.ljust(tab_width," ")} {PrintMsg.right if i != len(tab_lines)-1 else PrintMsg.right_bottom}')
            else:
                test_name = test_name.ljust(int(line_width_default/2)+int(len(test_name)/2)-1, PrintMsg.top)
                test_name = test_name.rjust(line_width_default-1 , PrintMsg.top)
                 
                LOG.info(f'{PrintMsg.left_top}{PrintMsg.blod}{test_name}{PrintMsg.right_top}{PrintMsg.rst_color}')
                LOG.info(f'{PrintMsg.left} region: {stack.region.ljust(line_width_default-len(" region: ")-1," ")}{PrintMsg.right}')
                LOG.info(
                    "{} status: {}{}{} ".format(
                    PrintMsg.left, PrintMsg.text_red_background_write, 
                    (stack.status + PrintMsg.rst_color).ljust(line_width_default-len(" status: ")+len(PrintMsg.rst_color)-1,' '), 
                    PrintMsg.right
                ))
                subsequent_indent = ' ' * 28
                status_reason = textwrap.fill(stack.status_reason, width=line_width_default-16, break_long_words=False, replace_whitespace=True, subsequent_indent=subsequent_indent)
                status_reason = PrintMsg.text_red_background_write + status_reason.replace('\n', f'{PrintMsg.rst_color}\n{PrintMsg.text_red_background_write}').replace(subsequent_indent,f'{PrintMsg.rst_color}{subsequent_indent}{PrintMsg.text_red_background_write}') + PrintMsg.rst_color
                LOG.info("{} status reason: {} {}\n".format(PrintMsg.left_bottom, status_reason, PrintMsg.rst_color))
    
    @staticmethod
    def _display_policies(policies: dict):  
         LOG.info(json.dumps(policies, sort_keys=True, indent=4, separators=(',', ': '), ensure_ascii=False))

    @staticmethod
    def _is_test_in_progress(status_dict, status_condition="IN_PROGRESS"):
        if not status_dict:
            return False
        if status_dict.get(status_condition):
            return True
        else:
            return False
