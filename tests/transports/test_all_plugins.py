# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
# This file is part of the AiiDA code.                                    #
#                                                                         #
# The code is hosted on GitHub at https://github.com/aiidateam/aiida-core #
# For further information on the license, see the LICENSE.txt file        #
# For further information please visit http://www.aiida.net               #
###########################################################################
# pylint: disable=too-many-lines,fixme
"""
This module contains a set of unittest test classes that can be loaded from
the plugin.
Every transport plugin should be able to pass all of these common tests.
Plugin specific tests will be written in the plugin itself.
"""
import io
import os
import random
import tempfile
import signal
import shutil
import string
import time
import unittest
import uuid

import psutil

from aiida.plugins import SchedulerFactory

# TODO : test for copy with pattern
# TODO : test for copy with/without patterns, overwriting folder
# TODO : test for exotic cases of copy with source = destination
# TODO : silly cases of copy/put/get from self to self


def get_all_custom_transports():
    """
    Autodiscover all custom transports defined in the variable
    plugin_transpors inside each test_* file in this folder.

    Therefore, do not move this function out of this file.

    :return: a dictionary of objects as defined in the various plugin_transport
      variables of the different files (the key is the module in which
      it was found)
    """
    import importlib

    modulename = __name__.rpartition('.')[0]
    this_full_fname = __file__
    thisdir, thisfname = os.path.split(this_full_fname)

    test_modules = [
        os.path.split(fname)[1][:-3]
        for fname in os.listdir(thisdir)
        if fname.endswith('.py') and fname.startswith('test_')
    ]

    # Remove this module: note that I should be careful because __file__, from
    # the second time on, is the pyc file rather than the py file
    thisbasename = os.path.splitext(thisfname)[0]
    try:
        test_modules.remove(thisbasename)
    except IndexError:
        print(f'Warning, this module ({thisbasename}) was not found!')

    all_custom_transports = {}
    for module in test_modules:
        module = importlib.import_module('.'.join([modulename, module]))
        custom_transport = module.__dict__.get('plugin_transport', None)
        if custom_transport is None:
            print(f'Define the plugin_transport variable inside the {module} module!')
        else:
            all_custom_transports[module] = custom_transport

    return all_custom_transports


def run_for_all_plugins(actual_test_method):
    """
    Decorator method that actually run the methods with an additional
    parameter (custom_transport), once for every custom_transport defined
    in the test_* files [except this one].
    """

    class CollectiveException(Exception):
        pass

    all_custom_transports = get_all_custom_transports()

    def test_all_plugins(self):
        """
        The wrapper function that calls the subfunction for each transport.
        """
        exceptions = []
        for tr_name, custom_transport in all_custom_transports.items():
            try:
                actual_test_method(self, custom_transport)
            except Exception as exception:  # pylint: disable=broad-except
                import traceback
                exceptions.append((exception, traceback.format_exc(), tr_name))

        if exceptions:
            if all(isinstance(exc[0], AssertionError) for exc in exceptions):
                exception_to_raise = AssertionError
            else:
                exception_to_raise = CollectiveException

            messages = ['*** At least one test for a subplugin failed. See below ***', '']
            for exc in exceptions:
                messages.append(f"*** [For plugin {exc[2]}]: Exception '{type(exc[0]).__name__}': {exc[0]}")
                messages.append(exc[1])

            raise exception_to_raise('\n'.join(messages))

    return test_all_plugins


class TestBasicFunctionality(unittest.TestCase):
    """
    Tests to check basic functionality of transports.
    """

    @run_for_all_plugins
    def test_is_open(self, custom_transport):
        """Test that the is_open property works."""
        self.assertFalse(custom_transport.is_open)

        with custom_transport:
            self.assertTrue(custom_transport.is_open)

        self.assertFalse(custom_transport.is_open)


class TestDirectoryManipulation(unittest.TestCase):
    """
    Tests to check, create and delete folders.
    """

    @run_for_all_plugins
    def test_makedirs(self, custom_transport):
        """
        Verify the functioning of makedirs command
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            transport.chdir(location)

            self.assertEqual(location, transport.getcwd())
            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)
            transport.mkdir(directory)
            transport.chdir(directory)

            # define folder structure
            dir_tree = os.path.join('1', '2')
            # I create the tree
            transport.makedirs(dir_tree)
            # verify the existence
            self.assertTrue(transport.isdir('1'))
            self.assertTrue(dir_tree)

            # try to recreate the same folder
            with self.assertRaises(OSError):
                transport.makedirs(dir_tree)

            # recreate but with ignore flag
            transport.makedirs(dir_tree, True)

            transport.rmdir(dir_tree)
            transport.rmdir('1')

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_rmtree(self, custom_transport):
        """
        Verify the functioning of rmtree command
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            transport.chdir(location)

            self.assertEqual(location, transport.getcwd())
            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)
            transport.mkdir(directory)
            transport.chdir(directory)

            # define folder structure
            dir_tree = os.path.join('1', '2')
            # I create the tree
            transport.makedirs(dir_tree)
            # remove it
            transport.rmtree('1')
            # verify the removal
            self.assertFalse(transport.isdir('1'))

            # also tests that it works with a single file
            # create file
            local_file_name = 'file.txt'
            text = 'Viva Verdi\n'
            with open(os.path.join(transport.getcwd(), local_file_name), 'w', encoding='utf8') as fhandle:
                fhandle.write(text)
            # remove it
            transport.rmtree(local_file_name)
            # verify the removal
            self.assertFalse(transport.isfile(local_file_name))

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_listdir(self, custom_transport):
        """
        create directories, verify listdir, delete a folder with subfolders
        """
        with custom_transport as trans:
            # We cannot use tempfile.mkdtemp because we're on a remote folder
            location = trans.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            trans.chdir(location)

            self.assertEqual(location, trans.getcwd())
            while trans.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)
            trans.mkdir(directory)
            trans.chdir(directory)
            list_of_dir = ['1', '-f a&', 'as', 'a2', 'a4f']
            list_of_files = ['a', 'b']
            for this_dir in list_of_dir:
                trans.mkdir(this_dir)
            for fname in list_of_files:
                with tempfile.NamedTemporaryFile() as tmpf:
                    # Just put an empty file there at the right file name
                    trans.putfile(tmpf.name, fname)

            list_found = trans.listdir('.')

            self.assertTrue(sorted(list_found) == sorted(list_of_dir + list_of_files))

            self.assertTrue(sorted(trans.listdir('.', 'a*')), sorted(['as', 'a2', 'a4f']))
            self.assertTrue(sorted(trans.listdir('.', 'a?')), sorted(['as', 'a2']))
            self.assertTrue(sorted(trans.listdir('.', 'a[2-4]*')), sorted(['a2', 'a4f']))

            for this_dir in list_of_dir:
                trans.rmdir(this_dir)

            for this_file in list_of_files:
                trans.remove(this_file)

            trans.chdir('..')
            trans.rmdir(directory)

    @run_for_all_plugins
    def test_listdir_withattributes(self, custom_transport):
        """
        create directories, verify listdir_withattributes, delete a folder with subfolders
        """

        def simplify_attributes(data):
            """
            Take data from listdir_withattributes and return a dictionary
            {fname: isdir}

            :param data: the output of listdir_withattributes
            :return: dictionary: the key is a filename, the value is True if it's a directory, False otherwise
            """
            return {_['name']: _['isdir'] for _ in data}

        with custom_transport as trans:
            # We cannot use tempfile.mkdtemp because we're on a remote folder
            location = trans.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            trans.chdir(location)

            self.assertEqual(location, trans.getcwd())
            while trans.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)
            trans.mkdir(directory)
            trans.chdir(directory)
            list_of_dir = ['1', '-f a&', 'as', 'a2', 'a4f']
            list_of_files = ['a', 'b']
            for this_dir in list_of_dir:
                trans.mkdir(this_dir)
            for fname in list_of_files:
                with tempfile.NamedTemporaryFile() as tmpf:
                    # Just put an empty file there at the right file name
                    trans.putfile(tmpf.name, fname)

            comparison_list = {k: True for k in list_of_dir}
            for k in list_of_files:
                comparison_list[k] = False
            self.assertTrue(simplify_attributes(trans.listdir_withattributes('.')), comparison_list)

            self.assertTrue(
                simplify_attributes(trans.listdir_withattributes('.', 'a*')), {
                    'as': True,
                    'a2': True,
                    'a4f': True,
                    'a': False
                }
            )
            self.assertTrue(simplify_attributes(trans.listdir_withattributes('.', 'a?')), {'as': True, 'a2': True})
            self.assertTrue(
                simplify_attributes(trans.listdir_withattributes('.', 'a[2-4]*')), {
                    'a2': True,
                    'a4f': True
                }
            )

            for this_dir in list_of_dir:
                trans.rmdir(this_dir)

            for this_file in list_of_files:
                trans.remove(this_file)

            trans.chdir('..')
            trans.rmdir(directory)

    @run_for_all_plugins
    def test_dir_creation_deletion(self, custom_transport):
        """Test creating and deleting directories."""
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            transport.chdir(location)

            self.assertEqual(location, transport.getcwd())
            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)
            transport.mkdir(directory)

            with self.assertRaises(OSError):
                # I create twice the same directory
                transport.mkdir(directory)

            transport.isdir(directory)
            self.assertFalse(transport.isfile(directory))
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_dir_copy(self, custom_transport):
        """
        Verify if in the copy of a directory also the protection bits
        are carried over
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            transport.chdir(location)

            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)
            transport.mkdir(directory)

            dest_directory = f'{directory}_copy'
            transport.copy(directory, dest_directory)

            with self.assertRaises(ValueError):
                transport.copy(directory, '')

            with self.assertRaises(ValueError):
                transport.copy('', directory)

            transport.rmdir(directory)
            transport.rmdir(dest_directory)

    @run_for_all_plugins
    def test_dir_permissions_creation_modification(self, custom_transport):  # pylint: disable=invalid-name
        """
        verify if chmod raises IOError when trying to change bits on a
        non-existing folder
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            transport.chdir(location)

            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            # create directory with non default permissions
            transport.mkdir(directory)

            # change permissions
            transport.chmod(directory, 0o777)

            # test if the security bits have changed
            self.assertEqual(transport.get_mode(directory), 0o777)

            # change permissions
            transport.chmod(directory, 0o511)

            # test if the security bits have changed
            self.assertEqual(transport.get_mode(directory), 0o511)

            # TODO : bug in paramiko. When changing the directory to very low \
            # I cannot set it back to higher permissions

            # TODO: probably here we should then check for
            # the new directory modes. To see if we want a higher
            # level function to ask for the mode, or we just
            # use get_attribute
            transport.chdir(directory)

            # change permissions of an empty string, non existing folder.
            fake_dir = ''
            with self.assertRaises(IOError):
                transport.chmod(fake_dir, 0o777)

            fake_dir = 'pippo'
            with self.assertRaises(IOError):
                # chmod to a non existing folder
                transport.chmod(fake_dir, 0o777)

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_dir_reading_permissions(self, custom_transport):
        """
        Try to enter a directory with no read permissions.
        Verify that the cwd has not changed after failed try.
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            directory = 'temp_dir_test'
            transport.chdir(location)

            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            # create directory with non default permissions
            transport.mkdir(directory)

            # change permissions to low ones
            transport.chmod(directory, 0)

            # test if the security bits have changed
            self.assertEqual(transport.get_mode(directory), 0)

            old_cwd = transport.getcwd()

            with self.assertRaises(IOError):
                transport.chdir(directory)

            new_cwd = transport.getcwd()

            self.assertEqual(old_cwd, new_cwd)

            # TODO : the test leaves a directory even if it is successful
            #        The bug is in paramiko. After lowering the permissions,
            #        I cannot restore them to higher values
            # transport.rmdir(directory)

    @run_for_all_plugins
    def test_isfile_isdir_to_empty_string(self, custom_transport):
        """
        I check that isdir or isfile return False when executed on an
        empty string
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            transport.chdir(location)
            self.assertFalse(transport.isdir(''))
            self.assertFalse(transport.isfile(''))

    @run_for_all_plugins
    def test_isfile_isdir_to_non_existing_string(self, custom_transport):
        """
        I check that isdir or isfile return False when executed on an
        empty string
        """
        with custom_transport as transport:
            location = transport.normalize(os.path.join('/', 'tmp'))
            transport.chdir(location)
            fake_folder = 'pippo'
            self.assertFalse(transport.isfile(fake_folder))
            self.assertFalse(transport.isdir(fake_folder))
            with self.assertRaises(IOError):
                transport.chdir(fake_folder)

    @run_for_all_plugins
    def test_chdir_to_empty_string(self, custom_transport):
        """
        I check that if I pass an empty string to chdir, the cwd does
        not change (this is a paramiko default behavior), but getcwd()
        is still correctly defined.
        """
        with custom_transport as transport:
            new_dir = transport.normalize(os.path.join('/', 'tmp'))
            transport.chdir(new_dir)
            transport.chdir('')
            self.assertEqual(new_dir, transport.getcwd())


class TestPutGetFile(unittest.TestCase):
    """
    Test to verify whether the put and get functions behave correctly on files.
    1) they work
    2) they need abs paths where necessary, i.e. for local paths
    3) they reject empty strings
    """

    @run_for_all_plugins
    def test_put_and_get(self, custom_transport):
        """Test putting and getting files."""
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)
            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            transport.mkdir(directory)
            transport.chdir(directory)

            local_file_name = os.path.join(local_dir, directory, 'file.txt')
            remote_file_name = 'file_remote.txt'
            retrieved_file_name = os.path.join(local_dir, directory, 'file_retrieved.txt')

            text = 'Viva Verdi\n'
            with open(local_file_name, 'w', encoding='utf8') as fhandle:
                fhandle.write(text)

            # here use full path in src and dst
            transport.put(local_file_name, remote_file_name)
            transport.get(remote_file_name, retrieved_file_name)
            transport.putfile(local_file_name, remote_file_name)
            transport.getfile(remote_file_name, retrieved_file_name)

            list_of_files = transport.listdir('.')
            # it is False because local_file_name has the full path,
            # while list_of_files has not
            self.assertFalse(local_file_name in list_of_files)
            self.assertTrue(remote_file_name in list_of_files)
            self.assertFalse(retrieved_file_name in list_of_files)

            os.remove(local_file_name)
            transport.remove(remote_file_name)
            os.remove(retrieved_file_name)

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_put_get_abs_path(self, custom_transport):
        """
        test of exception for non existing files and abs path
        """
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)
            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            transport.mkdir(directory)
            transport.chdir(directory)

            partial_file_name = 'file.txt'
            local_file_name = os.path.join(local_dir, directory, 'file.txt')
            remote_file_name = 'file_remote.txt'
            retrieved_file_name = os.path.join(local_dir, directory, 'file_retrieved.txt')

            fhandle = open(local_file_name, 'w', encoding='utf8')
            fhandle.close()

            # partial_file_name is not an abs path
            with self.assertRaises(ValueError):
                transport.put(partial_file_name, remote_file_name)
            with self.assertRaises(ValueError):
                transport.putfile(partial_file_name, remote_file_name)

            # retrieved_file_name does not exist
            with self.assertRaises(OSError):
                transport.put(retrieved_file_name, remote_file_name)
            with self.assertRaises(OSError):
                transport.putfile(retrieved_file_name, remote_file_name)

            # remote_file_name does not exist
            with self.assertRaises(IOError):
                transport.get(remote_file_name, retrieved_file_name)
            with self.assertRaises(IOError):
                transport.getfile(remote_file_name, retrieved_file_name)

            transport.put(local_file_name, remote_file_name)
            transport.putfile(local_file_name, remote_file_name)

            # local filename is not an abs path
            with self.assertRaises(ValueError):
                transport.get(remote_file_name, 'delete_me.txt')
            with self.assertRaises(ValueError):
                transport.getfile(remote_file_name, 'delete_me.txt')

            transport.remove(remote_file_name)
            os.remove(local_file_name)

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_put_get_empty_string(self, custom_transport):
        """
        test of exception put/get of empty strings
        """
        # TODO : verify the correctness of \n at the end of a file
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)
            while transport.isdir(directory):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            transport.mkdir(directory)
            transport.chdir(directory)

            local_file_name = os.path.join(local_dir, directory, 'file_local.txt')
            remote_file_name = 'file_remote.txt'
            retrieved_file_name = os.path.join(local_dir, directory, 'file_retrieved.txt')

            text = 'Viva Verdi\n'
            with open(local_file_name, 'w', encoding='utf8') as fhandle:
                fhandle.write(text)

            # localpath is an empty string
            # ValueError because it is not an abs path
            with self.assertRaises(ValueError):
                transport.put('', remote_file_name)
            with self.assertRaises(ValueError):
                transport.putfile('', remote_file_name)

            # remote path is an empty string
            with self.assertRaises(IOError):
                transport.put(local_file_name, '')
            with self.assertRaises(IOError):
                transport.putfile(local_file_name, '')

            transport.put(local_file_name, remote_file_name)
            # overwrite the remote_file_name
            transport.putfile(local_file_name, remote_file_name)

            # remote path is an empty string
            with self.assertRaises(IOError):
                transport.get('', retrieved_file_name)
            with self.assertRaises(IOError):
                transport.getfile('', retrieved_file_name)

            # local path is an empty string
            # ValueError because it is not an abs path
            with self.assertRaises(ValueError):
                transport.get(remote_file_name, '')
            with self.assertRaises(ValueError):
                transport.getfile(remote_file_name, '')

            # TODO : get doesn't retrieve empty files.
            # Is it what we want?
            transport.get(remote_file_name, retrieved_file_name)
            # overwrite retrieved_file_name
            transport.getfile(remote_file_name, retrieved_file_name)

            os.remove(local_file_name)
            transport.remove(remote_file_name)
            # If it couldn't end the copy, it leaves what he did on
            # local file
            self.assertTrue('file_retrieved.txt' in transport.listdir('.'))
            os.remove(retrieved_file_name)

            transport.chdir('..')
            transport.rmdir(directory)


class TestPutGetTree(unittest.TestCase):
    """
    Test to verify whether the put and get functions behave correctly on folders.
    1) they work
    2) they need abs paths where necessary, i.e. for local paths
    3) they reject empty strings
    """

    @run_for_all_plugins
    def test_put_and_get(self, custom_transport):
        """Test putting and getting files."""
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:

            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            local_subfolder = os.path.join(local_dir, directory, 'tmp1')
            remote_subfolder = 'tmp2'
            retrieved_subfolder = os.path.join(local_dir, directory, 'tmp3')

            os.mkdir(os.path.join(local_dir, directory))
            os.mkdir(os.path.join(local_dir, directory, local_subfolder))

            transport.chdir(directory)

            local_file_name = os.path.join(local_subfolder, 'file.txt')

            text = 'Viva Verdi\n'
            with open(local_file_name, 'w', encoding='utf8') as fhandle:
                fhandle.write(text)

            # here use full path in src and dst
            for i in range(2):
                if i == 0:
                    transport.put(local_subfolder, remote_subfolder)
                    transport.get(remote_subfolder, retrieved_subfolder)
                else:
                    transport.puttree(local_subfolder, remote_subfolder)
                    transport.gettree(remote_subfolder, retrieved_subfolder)

                # Here I am mixing the local with the remote fold
                list_of_dirs = transport.listdir('.')
                # # it is False because local_file_name has the full path,
                # # while list_of_files has not
                self.assertFalse(local_subfolder in list_of_dirs)
                self.assertTrue(remote_subfolder in list_of_dirs)
                self.assertFalse(retrieved_subfolder in list_of_dirs)
                self.assertTrue('tmp1' in list_of_dirs)
                self.assertTrue('tmp3' in list_of_dirs)

                list_pushed_file = transport.listdir('tmp2')
                list_retrieved_file = transport.listdir('tmp3')
                self.assertTrue('file.txt' in list_pushed_file)
                self.assertTrue('file.txt' in list_retrieved_file)

            shutil.rmtree(local_subfolder)
            shutil.rmtree(retrieved_subfolder)
            transport.rmtree(remote_subfolder)

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_put_and_get_overwrite(self, custom_transport):
        """Test putting and getting files with overwrites."""
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            local_subfolder = os.path.join(local_dir, directory, 'tmp1')
            remote_subfolder = 'tmp2'
            retrieved_subfolder = os.path.join(local_dir, directory, 'tmp3')

            os.mkdir(os.path.join(local_dir, directory))
            os.mkdir(os.path.join(local_dir, directory, local_subfolder))

            transport.chdir(directory)

            local_file_name = os.path.join(local_subfolder, 'file.txt')

            text = 'Viva Verdi\n'
            with open(local_file_name, 'w', encoding='utf8') as fhandle:
                fhandle.write(text)

            transport.put(local_subfolder, remote_subfolder)
            transport.get(remote_subfolder, retrieved_subfolder)

            # by defaults rewrite everything
            transport.put(local_subfolder, remote_subfolder)
            transport.get(remote_subfolder, retrieved_subfolder)

            with self.assertRaises(OSError):
                transport.put(local_subfolder, remote_subfolder, overwrite=False)
            with self.assertRaises(OSError):
                transport.get(remote_subfolder, retrieved_subfolder, overwrite=False)
            with self.assertRaises(OSError):
                transport.puttree(local_subfolder, remote_subfolder, overwrite=False)
            with self.assertRaises(OSError):
                transport.gettree(remote_subfolder, retrieved_subfolder, overwrite=False)

            shutil.rmtree(local_subfolder)
            shutil.rmtree(retrieved_subfolder)
            transport.rmtree(remote_subfolder)
            # transport.rmtree(remote_subfolder)
            # here I am mixing inevitably the local and the remote folder
            transport.chdir('..')
            transport.rmtree(directory)

    @run_for_all_plugins
    def test_copy(self, custom_transport):
        """Test copying."""
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            transport.mkdir(directory)
            transport.chdir(directory)

            local_base_dir = os.path.join(local_dir, directory, 'local')
            os.mkdir(local_base_dir)

            # first test put: I create three files in local
            file_1 = os.path.join(local_base_dir, 'a.txt')
            file_2 = os.path.join(local_base_dir, 'b.tmp')
            file_3 = os.path.join(local_base_dir, 'c.txt')
            text = 'Viva Verdi\n'
            for filename in [file_1, file_2, file_3]:
                with open(filename, 'w', encoding='utf8') as fhandle:
                    fhandle.write(text)

            # first test the copy. Copy of two files matching patterns, into a folder
            transport.copy(os.path.join('local', '*.txt'), '.')
            self.assertEqual(set(['a.txt', 'c.txt', 'local']), set(transport.listdir('.')))
            transport.remove('a.txt')
            transport.remove('c.txt')
            # second test copy. Copy of two folders
            transport.copy('local', 'prova')
            self.assertEqual(set(['prova', 'local']), set(transport.listdir('.')))
            self.assertEqual(set(['a.txt', 'b.tmp', 'c.txt']), set(transport.listdir('prova')))
            transport.rmtree('prova')
            # third test copy. Can copy one file into a new file
            transport.copy(os.path.join('local', '*.tmp'), 'prova')
            self.assertEqual(set(['prova', 'local']), set(transport.listdir('.')))
            transport.remove('prova')
            # fourth test copy: can't copy more than one file on the same file,
            # i.e., the destination should be a folder
            with self.assertRaises(OSError):
                transport.copy(os.path.join('local', '*.txt'), 'prova')
            # fifth test, copying one file into a folder
            transport.mkdir('prova')
            transport.copy(os.path.join('local', 'a.txt'), 'prova')
            self.assertEqual(set(transport.listdir('prova')), set(['a.txt']))
            transport.rmtree('prova')
            # sixth test, copying one file into a file
            transport.copy(os.path.join('local', 'a.txt'), 'prova')
            self.assertTrue(transport.isfile('prova'))
            transport.remove('prova')
            # copy of folder into an existing folder
            # NOTE: the command cp has a different behavior on Mac vs Ubuntu
            # tests performed locally on a Mac may result in a failure.
            transport.mkdir('prova')
            transport.copy('local', 'prova')
            self.assertEqual(set(['local']), set(transport.listdir('prova')))
            self.assertEqual(set(['a.txt', 'b.tmp', 'c.txt']), set(transport.listdir(os.path.join('prova', 'local'))))
            transport.rmtree('prova')
            # exit
            transport.chdir('..')
            transport.rmtree(directory)

    @run_for_all_plugins
    def test_put(self, custom_transport):
        """Test putting files."""
        # pylint: disable=too-many-statements
        # exactly the same tests of copy, just with the put function
        # and therefore the local path must be absolute
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            transport.mkdir(directory)
            transport.chdir(directory)

            local_base_dir = os.path.join(local_dir, directory, 'local')
            os.mkdir(local_base_dir)

            # first test put: I create three files in local
            file_1 = os.path.join(local_base_dir, 'a.txt')
            file_2 = os.path.join(local_base_dir, 'b.tmp')
            file_3 = os.path.join(local_base_dir, 'c.txt')
            text = 'Viva Verdi\n'
            for filename in [file_1, file_2, file_3]:
                with open(filename, 'w', encoding='utf8') as fhandle:
                    fhandle.write(text)

            # first test putransport. Copy of two files matching patterns, into a folder
            transport.put(os.path.join(local_base_dir, '*.txt'), '.')
            self.assertEqual(set(['a.txt', 'c.txt', 'local']), set(transport.listdir('.')))
            transport.remove('a.txt')
            transport.remove('c.txt')
            # second. Copy of folder into a non existing folder
            transport.put(local_base_dir, 'prova')
            self.assertEqual(set(['prova', 'local']), set(transport.listdir('.')))
            self.assertEqual(set(['a.txt', 'b.tmp', 'c.txt']), set(transport.listdir('prova')))
            transport.rmtree('prova')
            # third. copy of folder into an existing folder
            transport.mkdir('prova')
            transport.put(local_base_dir, 'prova')
            self.assertEqual(set(['prova', 'local']), set(transport.listdir('.')))
            self.assertEqual(set(['local']), set(transport.listdir('prova')))
            self.assertEqual(set(['a.txt', 'b.tmp', 'c.txt']), set(transport.listdir(os.path.join('prova', 'local'))))
            transport.rmtree('prova')
            # third test copy. Can copy one file into a new file
            transport.put(os.path.join(local_base_dir, '*.tmp'), 'prova')
            self.assertEqual(set(['prova', 'local']), set(transport.listdir('.')))
            transport.remove('prova')
            # fourth test copy: can't copy more than one file on the same file,
            # i.e., the destination should be a folder
            with self.assertRaises(OSError):
                transport.put(os.path.join(local_base_dir, '*.txt'), 'prova')
            # copy of folder into file
            with open(os.path.join(local_dir, directory, 'existing.txt'), 'w', encoding='utf8') as fhandle:
                fhandle.write(text)
            with self.assertRaises(OSError):
                transport.put(os.path.join(local_base_dir), 'existing.txt')
            transport.remove('existing.txt')
            # fifth test, copying one file into a folder
            transport.mkdir('prova')
            transport.put(os.path.join(local_base_dir, 'a.txt'), 'prova')
            self.assertEqual(set(transport.listdir('prova')), set(['a.txt']))
            transport.rmtree('prova')
            # sixth test, copying one file into a file
            transport.put(os.path.join(local_base_dir, 'a.txt'), 'prova')
            self.assertTrue(transport.isfile('prova'))
            transport.remove('prova')

            # exit
            transport.chdir('..')
            transport.rmtree(directory)

    @run_for_all_plugins
    def test_get(self, custom_transport):
        """Test getting files."""
        # pylint: disable=too-many-statements
        # exactly the same tests of copy, just with the put function
        # and therefore the local path must be absolute
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            transport.mkdir(directory)
            transport.chdir(directory)

            local_base_dir = os.path.join(local_dir, directory, 'local')
            local_destination = os.path.join(local_dir, directory)
            os.mkdir(local_base_dir)

            # first test put: I create three files in local
            file_1 = os.path.join(local_base_dir, 'a.txt')
            file_2 = os.path.join(local_base_dir, 'b.tmp')
            file_3 = os.path.join(local_base_dir, 'c.txt')
            text = 'Viva Verdi\n'
            for filename in [file_1, file_2, file_3]:
                with open(filename, 'w', encoding='utf8') as fhandle:
                    fhandle.write(text)

            # first test put. Copy of two files matching patterns, into a folder
            transport.get(os.path.join('local', '*.txt'), local_destination)
            self.assertEqual(set(['a.txt', 'c.txt', 'local']), set(os.listdir(local_destination)))
            os.remove(os.path.join(local_destination, 'a.txt'))
            os.remove(os.path.join(local_destination, 'c.txt'))
            # second. Copy of folder into a non existing folder
            transport.get('local', os.path.join(local_destination, 'prova'))
            self.assertEqual(set(['prova', 'local']), set(os.listdir(local_destination)))
            self.assertEqual(
                set(['a.txt', 'b.tmp', 'c.txt']), set(os.listdir(os.path.join(local_destination, 'prova')))
            )
            shutil.rmtree(os.path.join(local_destination, 'prova'))
            # third. copy of folder into an existing folder
            os.mkdir(os.path.join(local_destination, 'prova'))
            transport.get('local', os.path.join(local_destination, 'prova'))
            self.assertEqual(set(['prova', 'local']), set(os.listdir(local_destination)))
            self.assertEqual(set(['local']), set(os.listdir(os.path.join(local_destination, 'prova'))))
            self.assertEqual(
                set(['a.txt', 'b.tmp', 'c.txt']), set(os.listdir(os.path.join(local_destination, 'prova', 'local')))
            )
            shutil.rmtree(os.path.join(local_destination, 'prova'))
            # third test copy. Can copy one file into a new file
            transport.get(os.path.join('local', '*.tmp'), os.path.join(local_destination, 'prova'))
            self.assertEqual(set(['prova', 'local']), set(os.listdir(local_destination)))
            os.remove(os.path.join(local_destination, 'prova'))
            # fourth test copy: can't copy more than one file on the same file,
            # i.e., the destination should be a folder
            with self.assertRaises(OSError):
                transport.get(os.path.join('local', '*.txt'), os.path.join(local_destination, 'prova'))
            # copy of folder into file
            with open(os.path.join(local_destination, 'existing.txt'), 'w', encoding='utf8') as fhandle:
                fhandle.write(text)
            with self.assertRaises(OSError):
                transport.get('local', os.path.join(local_destination, 'existing.txt'))
            os.remove(os.path.join(local_destination, 'existing.txt'))
            # fifth test, copying one file into a folder
            os.mkdir(os.path.join(local_destination, 'prova'))
            transport.get(os.path.join('local', 'a.txt'), os.path.join(local_destination, 'prova'))
            self.assertEqual(set(os.listdir(os.path.join(local_destination, 'prova'))), set(['a.txt']))
            shutil.rmtree(os.path.join(local_destination, 'prova'))
            # sixth test, copying one file into a file
            transport.get(os.path.join('local', 'a.txt'), os.path.join(local_destination, 'prova'))
            self.assertTrue(os.path.isfile(os.path.join(local_destination, 'prova')))
            os.remove(os.path.join(local_destination, 'prova'))

            # exit
            transport.chdir('..')
            transport.rmtree(directory)

    @run_for_all_plugins
    def test_put_get_abs_path(self, custom_transport):
        """
        test of exception for non existing files and abs path
        """
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            local_subfolder = os.path.join(local_dir, directory, 'tmp1')
            remote_subfolder = 'tmp2'
            retrieved_subfolder = os.path.join(local_dir, directory, 'tmp3')

            os.mkdir(os.path.join(local_dir, directory))
            os.mkdir(os.path.join(local_dir, directory, local_subfolder))

            transport.chdir(directory)
            local_file_name = os.path.join(local_subfolder, 'file.txt')

            fhandle = open(local_file_name, 'w', encoding='utf8')
            fhandle.close()

            # 'tmp1' is not an abs path
            with self.assertRaises(ValueError):
                transport.put('tmp1', remote_subfolder)
            with self.assertRaises(ValueError):
                transport.putfile('tmp1', remote_subfolder)
            with self.assertRaises(ValueError):
                transport.puttree('tmp1', remote_subfolder)

            # 'tmp3' does not exist
            with self.assertRaises(OSError):
                transport.put(retrieved_subfolder, remote_subfolder)
            with self.assertRaises(OSError):
                transport.putfile(retrieved_subfolder, remote_subfolder)
            with self.assertRaises(OSError):
                transport.puttree(retrieved_subfolder, remote_subfolder)

            # remote_file_name does not exist
            with self.assertRaises(IOError):
                transport.get('non_existing', retrieved_subfolder)
            with self.assertRaises(IOError):
                transport.getfile('non_existing', retrieved_subfolder)
            with self.assertRaises(IOError):
                transport.gettree('non_existing', retrieved_subfolder)

            transport.put(local_subfolder, remote_subfolder)

            # local filename is not an abs path
            with self.assertRaises(ValueError):
                transport.get(remote_subfolder, 'delete_me_tree')
            with self.assertRaises(ValueError):
                transport.getfile(remote_subfolder, 'delete_me_tree')
            with self.assertRaises(ValueError):
                transport.gettree(remote_subfolder, 'delete_me_tree')

            os.remove(os.path.join(local_subfolder, 'file.txt'))
            os.rmdir(local_subfolder)
            transport.rmtree(remote_subfolder)

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_put_get_empty_string(self, custom_transport):
        """
        test of exception put/get of empty strings
        """
        # TODO : verify the correctness of \n at the end of a file
        local_dir = os.path.join('/', 'tmp')
        remote_dir = local_dir
        directory = 'tmp_try'

        with custom_transport as transport:
            transport.chdir(remote_dir)

            while os.path.exists(os.path.join(local_dir, directory)):
                # I append a random letter/number until it is unique
                directory += random.choice(string.ascii_uppercase + string.digits)

            local_subfolder = os.path.join(local_dir, directory, 'tmp1')
            remote_subfolder = 'tmp2'
            retrieved_subfolder = os.path.join(local_dir, directory, 'tmp3')

            os.mkdir(os.path.join(local_dir, directory))
            os.mkdir(os.path.join(local_dir, directory, local_subfolder))

            transport.chdir(directory)
            local_file_name = os.path.join(local_subfolder, 'file.txt')

            text = 'Viva Verdi\n'
            with open(local_file_name, 'w', encoding='utf8') as fhandle:
                fhandle.write(text)

            # localpath is an empty string
            # ValueError because it is not an abs path
            with self.assertRaises(ValueError):
                transport.puttree('', remote_subfolder)

            # remote path is an empty string
            with self.assertRaises(IOError):
                transport.puttree(local_subfolder, '')

            transport.puttree(local_subfolder, remote_subfolder)

            # remote path is an empty string
            with self.assertRaises(IOError):
                transport.gettree('', retrieved_subfolder)

            # local path is an empty string
            # ValueError because it is not an abs path
            with self.assertRaises(ValueError):
                transport.gettree(remote_subfolder, '')

            # TODO : get doesn't retrieve empty files.
            # Is it what we want?
            transport.gettree(remote_subfolder, retrieved_subfolder)

            os.remove(os.path.join(local_subfolder, 'file.txt'))
            os.rmdir(local_subfolder)
            transport.remove(os.path.join(remote_subfolder, 'file.txt'))
            transport.rmdir(remote_subfolder)
            # If it couldn't end the copy, it leaves what he did on local file
            # here I am mixing local with remote
            self.assertTrue('file.txt' in transport.listdir('tmp3'))
            os.remove(os.path.join(retrieved_subfolder, 'file.txt'))
            os.rmdir(retrieved_subfolder)

            transport.chdir('..')
            transport.rmdir(directory)

    @run_for_all_plugins
    def test_gettree_nested_directory(self, custom_transport):  # pylint: disable=no-self-use
        """Test `gettree` for a nested directory."""
        with tempfile.TemporaryDirectory() as dir_remote, tempfile.TemporaryDirectory() as dir_local:
            content = b'dummy\ncontent'
            filepath = os.path.join(dir_remote, 'sub', 'path', 'filename.txt')
            os.makedirs(os.path.dirname(filepath))

            with open(filepath, 'wb') as handle:
                handle.write(content)

            with custom_transport as transport:
                transport.gettree(os.path.join(dir_remote, 'sub/path'), os.path.join(dir_local, 'sub/path'))


class TestExecuteCommandWait(unittest.TestCase):
    """
    Test some simple command executions and stdin/stdout management.

    It also checks for escaping of the folder names.
    """

    @run_for_all_plugins
    def test_exec_pwd(self, custom_transport):
        """
        I create a strange subfolder with a complicated name and
        then see if I can run pwd. This also checks the correct
        escaping of funny characters, both in the directory
        creation (which should be done by paramiko) and in the command
        execution (done in this module, in the _exec_command_internal function).
        """
        # Start value
        delete_at_end = False

        with custom_transport as transport:

            # To compare with: getcwd uses the normalized ('realpath') path
            location = transport.normalize('/tmp')
            subfolder = """_'s f"#"""  # A folder with characters to escape
            subfolder_fullpath = os.path.join(location, subfolder)

            transport.chdir(location)
            if not transport.isdir(subfolder):
                # Since I created the folder, I will remember to
                # delete it at the end of this test
                delete_at_end = True
                transport.mkdir(subfolder)

            self.assertTrue(transport.isdir(subfolder))
            transport.chdir(subfolder)

            self.assertEqual(subfolder_fullpath, transport.getcwd())
            retcode, stdout, stderr = transport.exec_command_wait('pwd')
            self.assertEqual(retcode, 0)
            # I have to strip it because 'pwd' returns a trailing \n
            self.assertEqual(stdout.strip(), subfolder_fullpath)
            self.assertEqual(stderr, '')

            if delete_at_end:
                transport.chdir(location)
                transport.rmdir(subfolder)

    @run_for_all_plugins
    def test_exec_with_stdin_string(self, custom_transport):
        """Test command execution with a stdin string."""
        test_string = str('some_test String')
        with custom_transport as transport:
            retcode, stdout, stderr = transport.exec_command_wait('cat', stdin=test_string)
            self.assertEqual(retcode, 0)
            self.assertEqual(stdout, test_string)
            self.assertEqual(stderr, '')

    @run_for_all_plugins
    def test_exec_with_stdin_unicode(self, custom_transport):
        """Test command execution with a unicode stdin string."""
        test_string = 'some_test String'
        with custom_transport as transport:
            retcode, stdout, stderr = transport.exec_command_wait('cat', stdin=test_string)
            self.assertEqual(retcode, 0)
            self.assertEqual(stdout, test_string)
            self.assertEqual(stderr, '')

    @run_for_all_plugins
    def test_exec_with_stdin_filelike(self, custom_transport):
        """Test command execution with a stdin from filelike."""
        test_string = 'some_test String'
        stdin = io.StringIO(test_string)
        with custom_transport as transport:
            retcode, stdout, stderr = transport.exec_command_wait('cat', stdin=stdin)
            self.assertEqual(retcode, 0)
            self.assertEqual(stdout, test_string)
            self.assertEqual(stderr, '')

    @run_for_all_plugins
    def test_exec_with_wrong_stdin(self, custom_transport):
        """Test command execution with incorrect stdin string."""
        # I pass a number
        with custom_transport as transport:
            with self.assertRaises(ValueError):
                transport.exec_command_wait('cat', stdin=1)


class TestDirectScheduler(unittest.TestCase):
    """
    Test how the direct scheduler works.

    While this is technically a scheduler test, I put it under the transport tests
    because 1) in reality I am testing the interaction of each transport with the
    direct scheduler; 2) the direct scheduler is always available; 3) I am reusing
    the infrastructure to test on multiple transport plugins.
    """

    @run_for_all_plugins
    def test_asynchronous_execution(self, custom_transport):
        """Test that the execution of a long(ish) command via the direct scheduler does not block.

        This is a regression test for #3094, where running a long job on the direct scheduler
        (via SSH) would lock the interpreter until the job was done.
        """
        # Use a unique name, using a UUID, to avoid concurrent tests (or very rapid
        # tests that follow each other) to overwrite the same destination
        script_fname = f'sleep-submit-{uuid.uuid4().hex}-{custom_transport.__class__.__name__}.sh'

        scheduler = SchedulerFactory('direct')()
        scheduler.set_transport(custom_transport)
        with custom_transport as transport:
            try:
                with tempfile.NamedTemporaryFile() as tmpf:
                    # Put a submission script that sleeps 10 seconds
                    tmpf.write(b'#!/bin/bash\nsleep 10\n')
                    tmpf.flush()

                    transport.chdir('/tmp')
                    transport.putfile(tmpf.name, script_fname)

                timestamp_before = time.time()
                job_id_string = scheduler.submit_from_script('/tmp', script_fname)

                elapsed_time = time.time() - timestamp_before
                # We want to get back control. If it takes < 5 seconds, it means that it is not blocking
                # as the job is taking at least 10 seconds. I put 5 as the machine could be slow (including the
                # SSH connection etc.) and I don't want to have false failures.
                # Actually, if the time is short, it could mean also that the execution failed!
                # So I double check later that the execution was successful.
                self.assertTrue(
                    elapsed_time < 5, 'Getting back control after remote execution took more than 5 seconds! '
                    'Probably submission is blocking'
                )

                # Check that the job is still running
                # Wait 0.2 more seconds, so that I don't do a super-quick check that might return True
                # even if it's not sleeping
                time.sleep(0.2)
                # Check that the job is still running - IMPORTANT, I'm assuming that all transports actually act
                # on the *same* local machine, and that the job_id is actually the process PID.
                # This needs to be adapted if:
                #    - a new transport plugin is tested and this does not test the same machine
                #    - a new scheduler is used and does not use the process PID, or the job_id of the 'direct' scheduler
                #      is not anymore simply the job PID
                job_id = int(job_id_string)
                self.assertTrue(
                    psutil.pid_exists(job_id), 'The job is not there after a bit more than 1 second! Probably it failed'
                )
            finally:
                # Clean up by killing the remote job.
                # This assumes it's on the same machine; if we add tests on a different machine,
                # we need to call 'kill' via the transport instead.
                # In reality it's not critical to remove it since it will end after 10 seconds of
                # sleeping, but this might avoid warnings (e.g. ResourceWarning)
                try:
                    os.kill(job_id, signal.SIGTERM)
                except ProcessLookupError:
                    # If the process is already dead (or has never run), I just ignore the error
                    pass

                # Also remove the script
                try:
                    transport.remove(f'/tmp/{script_fname}')
                except FileNotFoundError:
                    # If the file wasn't even created, I just ignore this error
                    pass