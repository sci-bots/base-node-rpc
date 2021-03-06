'''
.. versionadded:: v0.33
'''
from __future__ import absolute_import
from __future__ import print_function
import itertools as it
import struct
import time

from builtins import bytes
from six.moves import range
import numpy as np
import path_helpers as ph
import six

from .intel_hex import parse_intel_hex


def _data_as_list(data):
    '''
    Parameters
    ----------
    data : list or numpy.array or str
        Data bytes.

    Returns
    -------
    list
        List of integer byte values.
    '''
    if isinstance(data, np.ndarray):
        data = data.tobytes()
    if isinstance(data, six.string_types):
        data = list(bytes(data))
    return data


class TwiBootloader(object):
    def __init__(self, proxy, bootloader_address=0x29):
        '''
        Parameters
        ----------
        proxy : base_node_rpc.Proxy
        address : int
            I2C address of switching board.
        '''
        self.proxy = proxy
        self.bootloader_address = bootloader_address

    def abort_boot_timeout(self):
        '''
        Prevent bootloader from automatically starting application code.
        '''
        self.proxy.i2c_write(self.bootloader_address, 0x00)

    def start_application(self):
        '''
        Explicitly start application code.
        '''
        self.proxy.i2c_write(self.bootloader_address, [0x01, 0x80])

    def read_bootloader_version(self):
        '''
        Read ``twiboot`` version string.
        '''
        self.proxy.i2c_write(self.bootloader_address, 0x01)
        return self.proxy.i2c_read(self.bootloader_address, 16).tostring()

    def read_chip_info(self):
        '''
        Returns
        -------
        dict
            Information about device, including, e.g., sizes of memory regions.
        '''
        self.proxy.i2c_write(self.bootloader_address, [0x02, 0x00, 0x00, 0x00])
        data = self.proxy.i2c_read(self.bootloader_address, 8)
        return {
            'signature': data[:3].tolist(),
            'page_size': data[3],
            'flash_size': struct.unpack('>H', data[4:6])[0],
            'eeprom_size': struct.unpack('>H', data[6:8])[0]
        }

    def read_flash(self, address, n_bytes):
        """
        Read one or more flash bytes.

        Parameters
        ----------
        address : int
            Address in flash memory to read from.
        n_bytes : int
            Number of bytes to read.
        """
        addrh = address >> 8 & 0xFF
        addrl = address & 0xFF
        self.proxy.i2c_write(self.bootloader_address, [0x02, 0x01, addrh,
                                                       addrl])
        return self.proxy.i2c_read(self.bootloader_address, n_bytes)

    def read_eeprom(self, address, n_bytes):
        """
        Read one or more eeprom bytes

        Parameters
        ----------
        address : int
            Address in EEPROM to read from.
        n_bytes : int
            Number of bytes to read.
        """
        addrh = address >> 8 & 0xFF
        addrl = address & 0xFF
        self.proxy.i2c_write(self.bootloader_address, [0x02, 0x02, addrh,
                                                       addrl])
        return self.proxy.i2c_read(self.bootloader_address, n_bytes)

    def write_flash(self, address, page):
        """
        Write one flash page (128bytes on atmega328p).

        .. note::
            Page size can be queried by through :meth:`read_chip_info`.

        Parameters
        ----------
        address : int
            Address in EEPROM to write to.
        page : list or numpy.array or str
            Data to write.

            .. warning::
                Length **MUST** be equal to page size.
        """
        addrh = address >> 8 & 0xFF
        addrl = address & 0xFF
        page = _data_as_list(page)
        self.proxy.i2c_write(self.bootloader_address, [0x02, 0x01, addrh,
                                                       addrl] + page)

    def write_eeprom(self, address, data):
        """
        Write one or more eeprom bytes.

        Parameters
        ----------
        address : int
            Address in EEPROM to write to.
        data : list or numpy.array or str
            Data to write.

        See also
        --------
        :func:`_data_as_list`
        """
        addrh = address >> 8 & 0xFF
        addrl = address & 0xFF
        data = _data_as_list(data)
        self.proxy.i2c_write(self.bootloader_address, [0x02, 0x02, addrh,
                                                       addrl] + data)

    def write_firmware(self, firmware_path, verify=True, delay_s=0.02):
        '''
        Write `Intel HEX file`__ and split into pages.

        __ Intel HEX file: https://en.wikipedia.org/wiki/Intel_HEX

        Parameters
        ----------
        firmware_path : str
            Path of Intel HEX file to read.
        verify : bool, optional
            If ``True``, verify each page after it is written.
        delay_s : float, optional
            Time to wait between each write/read operation.

            This delay allows for operation to complete before triggering I2C
            next call.

        Raises
        ------
        IOError
            If a flash page write fails after 10 retry attempts.

            Delay is increased exponentially between operations from one
            attempt to the next.

        .. versionchanged:: 0.34
            Prior to version 0.34, if a page write failed while writing
            firmware to flash memory, an exception was raised immeidately.
            This approach is problematic, as it leaves the flash memory in a
            non-deterministic state which may prevent, for example, returning
            control to the bootloader.

            As of version 0.34, retry failed page writes up to 10 times,
            increasing the delay between operations exponentially from one
            attempt to the next.
        '''
        chip_info = self.read_chip_info()

        pages = load_pages(firmware_path, chip_info['page_size'])

        # At most, wait 100x the specified nominal delay during retries of
        # failed page writes.
        max_delay = max(1., 100. * delay_s)
        # Retry failed page writes up to 10 times, increasing the delay between
        # operations exponentially from one attempt to the next.
        delay_durations = np.logspace(np.log(delay_s) / np.log(10),
                                      np.log(max_delay) / np.log(10), num=10,
                                      base=10)

        for i, page_i in enumerate(pages):
            # If `verify` is `True`, retry failed page writes up to 10 times.
            for delay_j in delay_durations:
                print('Write page: %4d/%d     \r' % (i + 1, len(pages)),
                      end=' ')
                self.write_flash(i * chip_info['page_size'], page_i)
                # Delay to allow bootloader to finish writing to flash.
                time.sleep(delay_j)

                if not verify:
                    break
                print('Verify page: %4d/%d    \r' % (i + 1, len(pages)),
                      end=' ')
                # Verify written page.
                verify_data_i = self.read_flash(i * chip_info['page_size'],
                                                chip_info['page_size'])
                # Delay to allow bootloader to finish processing flash read.
                time.sleep(delay_j)
                try:
                    if (verify_data_i == page_i).all():
                        # Data page has been verified successfully.
                        break
                except AttributeError:
                    # Data lengths do not match.
                    pass
            else:
                raise IOError('Page write failed to verify for **all** '
                              'attempted delay durations.')


def load_pages(firmware_path, page_size):
    '''
    Load `Intel HEX file`__ and split into pages.

    __ Intel HEX file: https://en.wikipedia.org/wiki/Intel_HEX

    Parameters
    ----------
    firmware_path : str
        Path of Intel HEX file to read.
    page_size : int
        Size of each page.

    Returns
    -------
    list
        List of page contents, where each page is represented as a list of
        integer byte values.
    '''
    firmware_path = ph.path(firmware_path)
    with firmware_path.open('r') as input_:
        data = input_.read()

    df_data = parse_intel_hex(data)
    data_bytes = list(it.chain(*df_data.loc[df_data.record_type == 0, 'data']))

    pages = [data_bytes[i:i + page_size]
             for i in range(0, len(data_bytes), page_size)]

    # Pad end of last page with 0xFF to fill full page size.
    pages[-1].extend([0xFF] * (page_size - len(pages[-1])))
    return pages
